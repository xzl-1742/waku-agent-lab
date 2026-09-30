"""Assistant assertions and misleading excerpts cannot become durable quotes."""

import json
from types import SimpleNamespace

import pytest

from evals.helpers import make_waku, response, text_block
from waku.memory.batches import consolidate


@pytest.mark.parametrize("policy", ["legacy", "lifecycle"])
@pytest.mark.parametrize("fault", ["invented", "assistant", "negation", "subject", "episode"])
def test_unsupported_extraction_leaves_every_source_pending(tmp_path, policy, fault):
    app = make_waku(tmp_path, memory_policy=policy, consolidate_every=1,
                    client=SimpleNamespace(messages=SimpleNamespace()))
    source = "The assistant falsely claimed tools are unavailable."
    claim = "tools are unavailable"
    app.memory.log_chat(source, claim)
    fact = {"subject": "assistant", "content": source}
    episode = None if policy == "lifecycle" else ""
    if fault in ("invented", "assistant", "negation"):
        fact["content"] = "The log contains 512 bytes." if fault == "invented" else claim
    elif fault == "subject":
        fact["subject"] = "deployment succeeded"
    else:
        episode = "The tool executed successfully."
    if policy == "lifecycle":
        fact["source_ids"] = [2 if fault == "assistant" else 1]
        if episode:
            episode = {"summary": episode, "source_ids": [1]}
    app.memory.client.messages.create = lambda **kw: response([text_block(json.dumps({"facts": [fact], "episode": episode}))])
    app.memory.maybe_consolidate()
    for table in ("facts", "episodes", "memory_batches", "memory_evidence"):
        assert app.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert app.conn.execute("SELECT sum(consolidated) FROM chat_log").fetchone()[0] == 0


def test_each_fact_records_only_its_own_user_citation(tmp_path):
    app = make_waku(tmp_path, memory_policy="lifecycle", consolidate_every=2,
                    client=SimpleNamespace(messages=SimpleNamespace()))
    app.memory.log_chat("The port is 4200.", "Acknowledged")
    app.memory.log_chat("The budget is 350.", "Acknowledged")
    facts = [{"subject": "port", "content": "The port is 4200.", "source_ids": [1]},
             {"subject": "budget", "content": "The budget is 350.", "source_ids": [3]}]
    app.memory.client.messages.create = lambda **kw: response([text_block(json.dumps({"facts": facts, "episode": None}))])
    assert consolidate(app.memory) == 2
    assert [tuple(r) for r in app.conn.execute("SELECT memory_id,source_id FROM memory_evidence ORDER BY memory_id")] == [(1, "1"), (2, "3")]
