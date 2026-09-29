"""V4 decisions, evidence budgets and reads preserve V3 eligibility offline."""

import json

import pytest

from evals.helpers import ScriptedClient, make_waku, response, text_block, tool_block
from waku.memory.retrieval import tokens
from waku.memory.selective_gate import PROMPT, decide, validate
from waku.runtime.context import TurnStopped


def decision(retrieve=True, query="Alex", mode="search"):
    return {"retrieve": retrieve, "query": query, "reason": "personal context", "mode": mode}


def app_at(path, script=(), **kwargs):
    return make_waku(path, client=ScriptedClient(list(script)), retrieval_policy="selective", memory_policy="lifecycle",
                     consolidate_every=10000, **kwargs)


@pytest.mark.parametrize("text", ['{}', '{"retrieve":"false","query":"","reason":"skip","mode":"search"}',
                                  json.dumps(decision(False)), json.dumps(decision(True, "")),
                                  json.dumps(decision(True, "Alex", "recent")),
                                  'prefix ' + json.dumps(decision()),
                                  '{"retrieve":true,"retrieve":false,"query":"","reason":"x","mode":"search"}'])
def test_strict_gate_rejects_invalid_decisions(text):
    with pytest.raises(ValueError):
        validate(text)


@pytest.mark.parametrize("fault,expected", [("invalid", "invalid"), ("error", "error"), ("skip", "skip")])
def test_gate_failures_are_distinct_from_deliberate_skip(tmp_path, fault, expected):
    reply = json.dumps(decision(False, "")) if fault == "skip" else '{}'
    app = app_at(tmp_path, [response([text_block(reply)])])
    if fault == "error":
        def fail(**kwargs):
            raise OSError("synthetic outage")
        app.memory.client.messages.create = fail
    events = []
    app.memory.gated_retrieve("Alex", notify=lambda k, e: events.append((k, e)))
    gate = next(e for k, e in events if k == "gate")
    assert gate["status"] == expected
    assert gate["fallback"] == (fault != "skip")
    assert bool([e for k, e in events if k == "retrieval"]) == (fault != "skip")


def test_terminal_gate_error_never_falls_open(tmp_path):
    app = app_at(tmp_path)
    def fail(**kwargs):
        raise TurnStopped("suppression changed")
    app.memory.client.messages.create = fail
    with pytest.raises(TurnStopped, match="suppression"):
        app.memory.gated_retrieve("Alex")


def test_gate_hints_and_whole_request_are_bounded(tmp_path):
    app = app_at(tmp_path, context_policy="window", retrieval_gate_tokens=3000)
    calls, events = [], []
    def capture(**request):
        calls.append(request)
        return response([text_block(json.dumps(decision()))])
    app.memory.client.messages.create = capture
    decide(app.memory, "When do we meet him?", [{"role": "user", "content": "Alex " + "x" * 10000}],
           "Alex meeting " + "x" * 10000, lambda k, e: events.append(e))
    assert len(calls) == 1
    assert events[0]["estimated_input_tokens"] <= 3000
    assert events[0]["input_tokens"] is None
    app.settings.history_turns = 0
    decide(app.memory, "Next?", [{"role": "user", "content": "forbidden history"}], "forbidden checkpoint", lambda *args: None)
    assert "forbidden" not in calls[-1]["messages"][0]["content"]
    with pytest.raises(TurnStopped, match="gate input"):
        decide(app.memory, "x" * 10000, [], "", lambda *args: None)
    assert len(calls) == 2


def test_dialogue_reaches_gate_from_session(tmp_path):
    app = app_at(tmp_path)
    app.session.history = [{"role": "user", "content": "We discussed Alex."}]
    calls = []
    app.memory.client.messages.create = lambda **kwargs: calls.append(kwargs) or response([text_block(json.dumps(decision()))])
    app.session.build_system("What about him?")
    payload = json.loads(calls[0]["messages"][0]["content"][len(PROMPT):])
    assert payload["dialogue"][0]["content"] == "We discussed Alex."


def test_compact_gate_keeps_assistant_text_blocks(tmp_path):
    skip = response([text_block(json.dumps(decision(False, "")))])
    app = app_at(tmp_path, [skip, response([text_block("Alex picked Tuesday.")]),
                           skip, response([text_block("His name is Alex.")])], context_policy="compact",
                 retrieval_gate_tokens=4096)
    calls = []
    original = app.memory.client.messages.create
    app.memory.client.messages.create = lambda **kwargs: calls.append(kwargs) or original(**kwargs)
    app.respond("Who picked the date?")
    app.respond("What about him?")
    gates = [c for c in calls if isinstance(c["messages"][0]["content"], str)
             and c["messages"][0]["content"].startswith(PROMPT)]
    data = json.loads(gates[-1]["messages"][0]["content"][len(PROMPT):])
    assert {"role": "assistant", "content": "Alex picked Tuesday."} in data["dialogue"]


def test_gate_hints_exclude_tool_payloads_and_reasoning(tmp_path):
    app = app_at(tmp_path)
    calls = []
    app.memory.client.messages.create = lambda **kwargs: calls.append(kwargs) or response([text_block(json.dumps(decision()))])
    dialogue = [{"role": "assistant", "content": [{"type": "text", "text": "Alex picked Tuesday."},
                                                 {"type": "thinking", "thinking": "private reasoning"},
                                                 {"type": "tool_use", "input": {"value": "tool arguments"}}]},
                {"role": "user", "content": [{"type": "tool_result", "content": "tool output"}]}]
    decide(app.memory, "What about him?", dialogue, "", lambda *args: None)
    data = json.loads(calls[0]["messages"][0]["content"][len(PROMPT):])
    assert data["dialogue"] == [{"role": "assistant", "content": "Alex picked Tuesday."}]


@pytest.mark.parametrize("query,content", [("张伟", "昨天和张伟讨论部署。"), ("王敏", "我们与王敏约定周五验收。"),
                                          ("Muller", "Müller prefers mornings."), ("Ａｌｅｘ", "Alex likes tea."),
                                          ("Alex meeting", "Alex meets us Tuesday at 10."),
                                          ("garden flowers", "Gardens have a flower display.")])
def test_unicode_matching_inside_sentences(tmp_path, query, content):
    app = app_at(tmp_path)
    record = app.memory.facts.add("notes", content)
    assert app.memory.retrieval.rows(query)[0]["id"] == record


@pytest.mark.parametrize("query", ["", "!!!", "the and what", "请问 什么", "car", "Zelda"])
def test_empty_common_and_unknown_queries_do_not_return_recent_memory(tmp_path, query):
    app = app_at(tmp_path)
    app.memory.facts.add("home", "The carpet is red.")
    app.memory.episodes.add("The carpet arrived today", "2026-01-01")
    assert app.memory.retrieval.rows(query) == []
    assert len(app.memory.retrieval.rows("", "episode", recent=True)) == 1


def test_scope_validity_source_order_and_old_episode_search(tmp_path):
    app = app_at(tmp_path, project_id="alpha", retrieval_top_k=2)
    old = app.memory.lifecycle.add("Atlas", "Atlas port 3000", "consolidation")
    new = app.memory.lifecycle.add("Atlas", "Atlas port 4000", "correction")
    app.memory.lifecycle.add("Atlas", "Atlas port 9000", scope=("project", "beta"))
    assert [r["id"] for r in app.memory.retrieval.rows("Atlas port")] == [new, old]
    app.memory.episodes.add("Met Zhang about deployment", "2000-01-01")
    for _ in range(25):
        app.memory.episodes.add("Unrelated event", "2026-01-01")
    assert app.memory.retrieval.rows("Zhang", "episode")[0]["text"] == "Met Zhang about deployment"


def test_evidence_and_detail_pages_are_bounded_and_recheck_suppression(tmp_path):
    app = app_at(tmp_path, retrieval_tokens=512)
    text = "背景" * 1000 + "张伟负责部署" + "背景" * 1000
    record = app.memory.facts.add("work", text)
    payload = app.memory.retrieval.search("张伟")
    assert tokens(payload) <= 512
    assert "张伟" in payload["entries"][0]["text"]
    assert payload["entries"][0]["truncated"]
    tool = app.tools._tools["manage_memory"]
    page = json.loads(tool.fn(action="read", id=record, offset=2000, limit=10000))
    assert tokens(page) <= 512
    assert page["next_offset"] > 2000
    app.memory.facts.delete(record)
    assert "unavailable" in tool.fn(action="read", id=record, offset=2000, limit=3)


def test_recovery_search_quota_and_events_reset_per_turn(tmp_path):
    app = app_at(tmp_path)
    app.memory.facts.add("Alex", "Alex meets Tuesday")
    tool, events = app.tools._tools["manage_memory"], []
    for _ in range(2):
        assert json.loads(tool.fn(action="search", query="Alex", _notify=lambda k, e: events.append(e)))["entries"]
    assert "limit reached" in tool.fn(action="search", query="Alex")
    assert all(e["stage"] == "recovery" for e in events)
    app.memory.retrieval.reset()
    assert "entries" in tool.fn(action="search", query="Alex")


def test_main_loop_can_recover_after_gate_skip(tmp_path):
    app = app_at(tmp_path, [response([text_block(json.dumps(decision(False, "")))]),
                           response([tool_block("manage_memory", {"action": "search", "query": "Alex"})]),
                           response([text_block("Alex meets Tuesday.")])])
    app.memory.facts.add("Alex", "Alex meets Tuesday.")
    events = []
    result = app.respond("What did Alex decide?", observer=lambda k, e: events.append((k, e)))
    assert result.reply == "Alex meets Tuesday."
    assert any(k == "retrieval" and e["stage"] == "recovery" for k, e in events)


def test_selective_rejects_remote_guarantees(tmp_path):
    with pytest.raises(ValueError, match="requires SQLite"):
        app_at(tmp_path, semantic_store="mem0")


def test_legacy_gate_propagates_terminal_errors():
    from waku.memory.retrieval_gate import should_retrieve

    def fail(**kwargs):
        raise TurnStopped("do not repeat")
    client = ScriptedClient([])
    client.messages.create = fail
    with pytest.raises(TurnStopped):
        should_retrieve(client, "small", "Alex")


def test_valid_checkpoint_reaches_gate_after_restart(tmp_path):
    from evals.deterministic.test_compaction import SummaryClient, seed

    client = SummaryClient()
    app = make_waku(tmp_path, client=client, retrieval_policy="selective", memory_policy="lifecycle", context_policy="compact",
                     consolidate_every=10000, retrieval_gate_tokens=4096)
    seed(app)
    assert "checkpoint 1" in app.compact().reply
    app.conn.close()
    client = ScriptedClient([response([text_block(json.dumps(decision(False, "")))]), response([text_block("Continue")])])
    calls = []
    original = client.messages.create
    client.messages.create = lambda **kwargs: calls.append(kwargs) or original(**kwargs)
    app = make_waku(tmp_path, client=client, retrieval_policy="selective", memory_policy="lifecycle", context_policy="compact",
                     consolidate_every=10000, retrieval_gate_tokens=4096)
    assert app.respond("What was that constraint?").reply == "Continue"
    gate_data = json.loads(calls[0]["messages"][0]["content"][len(PROMPT):])
    assert "budget under 50" in gate_data["checkpoint"]
    old = app.memory.facts.add("budget", "Keep the budget under 50")
    app.memory.facts.delete(old)
    client._script = [response([text_block(json.dumps(decision(False, "")))]), response([text_block("New context")])]
    calls.clear()
    app.respond("Continue afresh")
    assert "budget under 50" not in json.dumps(calls)


def test_search_failure_is_reported_as_error_not_empty(tmp_path, monkeypatch):
    from waku.memory import lexical

    app = app_at(tmp_path)
    def fail(*args):
        raise OSError("synthetic backend outage")
    monkeypatch.setattr(lexical, "search", fail)
    events = []
    payload = app.memory.retrieval.search("Alex", notify=lambda k, e: events.append(e))
    assert payload["status"] == "error"
    assert events[0]["status"] == "error"


def test_detail_quota_and_scope_checks(tmp_path):
    app = app_at(tmp_path)
    other = app.memory.lifecycle.add("project", "Different project details", scope=("project", "elsewhere"))
    tool = app.tools._tools["manage_memory"]
    for _ in range(3):
        assert "unavailable" in tool.fn(action="read", id=other)
    assert "limit reached" in tool.fn(action="read", id=other)
