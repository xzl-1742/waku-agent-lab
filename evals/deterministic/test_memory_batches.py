"""Bounded extraction commits its memories, evidence and source markers together."""

import json
from types import SimpleNamespace

import pytest

from evals.helpers import make_waku, response, text_block
from waku.memory.batches import BATCH_PROMPT, consolidate
from waku.runtime.context import ContextBudget


class Extractor:
    def __init__(self):
        self.requests = []
        self.before_reply = lambda rows: None
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **request):
        self.requests.append(request)
        rows = json.loads(request["messages"][0]["content"][len(BATCH_PROMPT) + 1:])
        self.before_reply(rows)
        ids = [rows[0]["id"]]
        return response([text_block(json.dumps({
            "facts": [{"subject": "project", "content": rows[0]["content"], "source_ids": ids},
                      {"subject": "PROJECT", "content": rows[0]["content"], "source_ids": ids}],
            "episode": {"summary": rows[0]["content"], "source_ids": ids},
        }))])


def setup(path, **kwargs):
    client = Extractor()
    app = make_waku(path, client=client, memory_policy="lifecycle", consolidate_every=1, **kwargs)
    app.memory.log_chat("Keep the project port at 4200", "Port 4200", "alpha")
    return app, client


def test_batch_is_atomic_deduplicated_and_scoped_to_its_source_session(tmp_path):
    app, client = setup(tmp_path, memory_scope="session")
    app.memory.log_chat("Other session", "Other answer", "beta")
    client.before_reply = lambda rows: app.memory.log_chat("New arrival", "Waits for next batch", "alpha")
    assert consolidate(app.memory) == 1
    assert app.conn.execute("SELECT count(*) FROM episodes").fetchone()[0] == 1
    assert [r[0] for r in app.conn.execute("SELECT consolidated FROM chat_log ORDER BY id")] == [1, 1, 0, 0, 0, 0]
    fact = app.conn.execute("SELECT * FROM facts").fetchone()
    assert (fact["scope"], fact["scope_id"], fact["learned_session_id"]) == ("session", "alpha", "alpha")
    assert app.memory.facts.list() == []
    app.session.switch("alpha")
    assert len(app.memory.facts.list()) == 1
    assert {r[0] for r in app.conn.execute("SELECT source_id FROM memory_evidence")} == {"1"}
    assert json.loads(app.conn.execute("SELECT source_ids FROM memory_batches").fetchone()[0]) == [1, 2]


def test_failed_commit_rolls_back_every_write_then_retries_once(tmp_path):
    app, client = setup(tmp_path)
    app.conn.execute("CREATE TRIGGER fail_batch BEFORE INSERT ON memory_batches BEGIN SELECT RAISE(ABORT,'injected crash'); END")
    assert consolidate(app.memory) == 0
    for table in ("facts", "episodes", "memory_evidence", "memory_batches"):
        assert app.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert app.conn.execute("SELECT sum(consolidated) FROM chat_log").fetchone()[0] == 0
    app.conn.execute("DROP TRIGGER fail_batch")
    assert consolidate(app.memory) == 1
    assert consolidate(app.memory) == 0
    assert len(client.requests) == 2
    assert app.conn.execute("SELECT count(*) FROM memory_batches").fetchone()[0] == 1


@pytest.mark.parametrize("mutation", ["source", "generation"])
def test_stale_extraction_never_commits(tmp_path, mutation):
    app, client = setup(tmp_path)
    old = app.memory.facts.add("old", "discard this")

    def change(rows):
        if mutation == "generation":
            app.memory.facts.delete(old)
        else:
            app.conn.execute("UPDATE chat_log SET content='changed' WHERE id=?", (rows[0]["id"],))
            app.conn.commit()

    client.before_reply = change
    assert consolidate(app.memory) == 0
    assert app.conn.execute("SELECT count(*) FROM memory_batches").fetchone()[0] == 0
    assert app.conn.execute("SELECT sum(consolidated) FROM chat_log").fetchone()[0] == 0


def test_bounded_input_retains_unselected_exchanges(tmp_path):
    app, client = setup(tmp_path, consolidation_input_tokens=1600)
    for _ in range(10):
        app.memory.log_chat("x" * 1800, "y" * 1800, "alpha")
    assert consolidate(app.memory) == 1
    request = client.requests[0]
    assert ContextBudget.from_settings(app.settings).measure(request)["estimated_input_tokens"] <= 1600
    pending = app.conn.execute("SELECT count(*) FROM chat_log WHERE consolidated=0").fetchone()[0]
    assert 0 < pending < 22


def test_oversized_exchange_stays_pending_without_call(tmp_path):
    app, client = setup(tmp_path, consolidation_input_tokens=1024)
    app.conn.execute("UPDATE chat_log SET content=?", ("x" * 20000,))
    app.conn.commit()
    events = []
    assert consolidate(app.memory, lambda k, e: events.append(k)) == 0
    assert client.requests == []
    assert events == ["consolidation_blocked"]


def test_invalid_citations_do_not_mark_sources(tmp_path):
    app, _client = setup(tmp_path)
    app.memory.client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: response([text_block(
        '{"facts":[{"subject":"x","content":"y","source_ids":[999]}],"episode":null}')])) )
    assert consolidate(app.memory) == 0
    assert app.conn.execute("SELECT sum(consolidated) FROM chat_log").fetchone()[0] == 0
