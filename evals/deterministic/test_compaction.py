"""Offline continuation after bounded summaries, failures and provider limits."""

import json
from contextlib import contextmanager
from types import SimpleNamespace
from typing import ClassVar

import pytest

from evals.helpers import make_waku, response, text_block, tool_block
from waku.runtime.compaction import COMPACTION_PROMPT
from waku.runtime.context import encode, estimate_request, plain


class ContextLimit(Exception):
    status_code = 400
    body: ClassVar[dict] = {"error": {"code": "context_length_exceeded"}}


class SummaryClient:
    def __init__(self):
        self.messages = SimpleNamespace(create=self.create)
        self.requests, self.answers = [], []
        self.bad_summary = False

    def create(self, **kwargs):
        self.requests.append(plain(kwargs))
        if kwargs.get("system") == COMPACTION_PROMPT:
            if self.bad_summary:
                return response([text_block("{}")])
            payload = json.loads(kwargs["messages"][0]["content"])
            summary = payload["previous_summary"]
            for source in payload["sources"]:
                # The fake retains only evidence it has actually received.
                if "budget under 50" in source["text"]:
                    summary["constraints"] = [{"text": "Keep the budget under 50", "source_ids": [source["source_id"]]}]
            if not any(summary.values()):
                summary["goals"] = [{"text": "Continue the recorded task", "source_ids": [payload["sources"][0]["source_id"]]}]
            return response([text_block(encode(summary))])
        if "system" not in kwargs:
            return response([text_block('{"retrieve":false,"reason":"offline"}')])
        answer = self.answers.pop(0) if self.answers else response([text_block("Answer")])
        if isinstance(answer, Exception):
            raise answer
        return answer


def app_at(path, client=None, **kwargs):
    return make_waku(path, client=client or SummaryClient(), context_policy="compact", model="main", small_model="small",
                     consolidate_every=10000, **kwargs)


def seed(app, count=8, session="default", size=1000):
    for i in range(count):
        record = app.records.turn(session, "eval")
        record.message("user", ("Keep the budget under 50" if i == 0 else "Background") + "x" * size)
        record.message("assistant", "Acknowledged")


def test_manual_repeat_restart_switch_and_current_rules(tmp_path):
    client = SummaryClient()
    app = app_at(tmp_path, client)
    seed(app)
    events = []
    assert "checkpoint 1" in app.respond("/compact", observer=lambda k, e: events.append(k)).reply
    assert {"compaction_started", "compaction_call", "compaction_completed"} <= set(events)
    assert app.conn.execute("SELECT count(*) FROM chat_log").fetchone()[0] == 0
    seed(app, count=4)
    assert "checkpoint 2" in app.compact().reply
    saved = app.checkpoints.latest("default")
    app.conn.close()
    (tmp_path / "SOUL.md").write_text("Current rules: reply in French.", encoding="utf-8")
    app = app_at(tmp_path, client)
    app.respond("Continue")
    request = [r for r in client.requests if r.get("system", "").startswith("Current rules")][-1]
    assert "budget under 50" in request["system"]
    assert app.checkpoints.latest("default")["revision"] == saved["revision"]
    app.session.switch("other")
    app.respond("Unrelated")
    assert "budget under 50" not in client.requests[-1]["system"]
    app.session.switch("default")
    app.respond("Continue again")
    assert "budget under 50" in client.requests[-1]["system"]


def test_failed_summary_preserves_checkpoint_and_all_sources(tmp_path):
    client = SummaryClient()
    app = app_at(tmp_path, client)
    seed(app)
    app.compact()
    before = app.checkpoints.latest("default")
    seed(app)
    count = app.conn.execute("SELECT count(*) FROM session_messages").fetchone()[0]
    client.bad_summary = True
    assert "previous checkpoint" in app.compact().reply
    assert app.checkpoints.latest("default") == before
    assert app.conn.execute("SELECT count(*) FROM session_messages").fetchone()[0] == count


def test_automatic_compaction_retains_constraint(tmp_path):
    app = app_at(tmp_path, history_turns=5, compaction_keep_turns=2)
    seed(app, count=6)
    assert app.respond("Continue").reply == "Answer"
    assert app.checkpoints.latest("default") is not None
    final = app.client.client.requests[-1]
    assert "budget under 50" in final["system"]
    assert len(final["messages"]) == 5


def test_split_large_source_and_bound_each_summary_request(tmp_path):
    client = SummaryClient()
    app = app_at(tmp_path, client, compaction_keep_turns=0)
    seed(app, count=1, size=40000)
    assert "checkpoint 1" in app.compact().reply
    calls = [r for r in client.requests if r.get("system") == COMPACTION_PROMPT]
    segments = [s for r in calls for s in json.loads(r["messages"][0]["content"])["sources"]]
    first_id = segments[0]["source_id"]
    same = [s for s in segments if s["source_id"] == first_id]
    assert len(same) > 1
    assert same[0]["offset"] == 0
    assert sum(len(s["text"]) for s in same) == same[0]["total_chars"]
    assert all(estimate_request(r) <= 20000 for r in calls)


@pytest.mark.parametrize("stream", [False, True])
def test_provider_recovery_retries_only_request_after_tool(tmp_path, stream):
    client = SummaryClient()
    if stream:
        @contextmanager
        def stream_response(**kwargs):
            answer = client.create(**kwargs)
            yield SimpleNamespace(text_stream=iter([]), get_final_message=lambda: answer)
        client.messages.stream = stream_response
    app = app_at(tmp_path, client)
    seed(app, count=6, size=1800)
    client.answers = [response([tool_block("save_note", {"subject": "budget", "content": "50"})]),
                      ContextLimit("too long"), response([text_block("Recovered")])]
    assert app.respond("Save budget", stream=stream).reply == "Recovered"
    assert app.conn.execute("SELECT count(*) FROM facts WHERE subject='budget'").fetchone()[0] == 1
    answer_calls = [r for r in client.requests if r.get("system") and r["system"] != COMPACTION_PROMPT]
    assert len(answer_calls) == 3
    assert estimate_request(answer_calls[-1]) < estimate_request(answer_calls[-2])
    assert [m["role"] for m in answer_calls[-1]["messages"]] == ["user", "assistant", "user"]
    assert "Recorded executions" in answer_calls[-1]["system"]


def test_second_provider_overflow_stops_without_replay(tmp_path):
    client = SummaryClient()
    app = app_at(tmp_path, client)
    seed(app, count=6, size=1800)
    client.answers = [ContextLimit("too long"), ContextLimit("still too long")]
    assert "Provider context limit" in app.respond("Continue").reply
    assert len(client.answers) == 0


def test_huge_active_turn_stops_before_model(tmp_path):
    client = SummaryClient()
    app = app_at(tmp_path, client)
    assert "Context budget exceeded" in app.respond("x" * 80000).reply
    assert not any("system" in r for r in client.requests)
    assert app.checkpoints.latest("default") is None
    # The failed turn has an explicit terminal record. A small request can
    # continue after that completed error exchange is compressed.
    assert app.respond("Continue briefly").reply == "Answer"


def test_summary_call_limit_cannot_publish_partial_coverage(tmp_path):
    app = app_at(tmp_path, compaction_keep_turns=0, compaction_max_calls=1)
    seed(app, count=1, size=40000)
    assert "call limit" in app.compact().reply
    assert app.checkpoints.latest("default") is None


def test_unknown_action_stops_before_gate_or_model(tmp_path):
    client = SummaryClient()
    app = app_at(tmp_path, client)
    record = app.records.turn("default", "eval")
    record.message("user", "send")
    result_id = record.begin("call", "send", {})
    assert result_id in app.respond("Try again").reply
    assert client.requests == []


def test_smaller_window_on_restart_uses_persisted_sources(tmp_path):
    app = app_at(tmp_path)
    seed(app, count=8, size=2400)
    app.conn.close()
    app = app_at(tmp_path, context_window_tokens=20000, max_tokens=2048)
    assert app.respond("Continue").reply == "Answer"
    assert app.checkpoints.latest("default") is not None
    final = app.client.client.requests[-1]
    assert "budget under 50" in final["system"]
    assert estimate_request(final) <= 20000 - 2048 - 1024


def test_manual_command_uses_dashboard_lock_and_emits_done(tmp_path, monkeypatch):
    from waku.ops import dashboard

    app = app_at(tmp_path)
    seed(app)
    monkeypatch.setattr(dashboard, "get_agent", lambda: app)
    calls = []
    original = app.compact

    def compact(observer):
        assert dashboard.agent_lock.locked()
        return original(observer)

    monkeypatch.setattr(app, "compact", compact)
    dashboard.chat_stream("/compact", lambda kind, event: calls.append((kind, event)))
    assert calls[-1][0] == "done"
    assert "checkpoint 1" in calls[-1][1]["reply"]


def test_summary_usage_is_distinct_and_missing_usage_stays_unknown(tmp_path):
    from waku.ops.pricing import usage_summary

    app = app_at(tmp_path)
    seed(app)
    app.compact()
    entries = [json.loads(line) for line in (tmp_path / "usage.jsonl").read_text().splitlines()]
    assert all(row["kind"] == "compaction" and row["in"] is None for row in entries)
    assert usage_summary(tmp_path)["unmeasured_calls"] == len(entries)


@pytest.mark.parametrize("command", ["/compact extra", "/compact@waku extra"])
def test_compact_arguments_do_not_start_a_model_turn(tmp_path, command):
    app = app_at(tmp_path)
    assert "without arguments" in app.respond(command).reply
    assert app.client.client.requests == []


def test_failed_summary_call_still_has_timing_and_provenance(tmp_path, monkeypatch):
    app = app_at(tmp_path)
    seed(app)

    def fail(**kwargs):
        raise RuntimeError("synthetic summary failure")

    monkeypatch.setattr(app.client.client.messages, "create", fail)
    events = []
    assert "synthetic summary failure" in app.compact(lambda k, e: events.append((k, e))).reply
    call = next(e for k, e in events if k == "compaction_call")
    assert call["status"] == "failed" and call["elapsed_ms"] >= 0
    assert len(call["request_sha256"]) == 64
    assert call["input_tokens"] is None
    assert app.checkpoints.latest("default") is None


def test_zero_history_does_not_load_checkpoint_into_answer(tmp_path):
    app = app_at(tmp_path, history_turns=0)
    seed(app)
    app.compact()
    app.respond("A fresh request")
    final = app.client.client.requests[-1]
    assert "budget under 50" not in final["system"]
    assert len(final["messages"]) == 1


def test_custom_summary_model_uses_same_client_with_own_capacity(tmp_path):
    app = app_at(tmp_path, compaction_model="summary", compaction_context_tokens=14000)
    seed(app)
    assert "checkpoint 1" in app.compact().reply
    calls = [r for r in app.client.client.requests if r.get("system") == COMPACTION_PROMPT]
    assert calls and all(r["model"] == "summary" for r in calls)
    assert all(estimate_request(r) + 2048 + 1024 <= 14000 for r in calls)
