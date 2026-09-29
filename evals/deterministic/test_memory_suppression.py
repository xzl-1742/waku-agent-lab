"""Forgetting excludes derived context while preserving original records."""

import json

import pytest

from evals.deterministic.test_compaction import SummaryClient, seed
from evals.helpers import make_waku, response, tool_block
from waku.runtime.context import TurnStopped, encode


@pytest.mark.parametrize("context", ["window", "budget", "compact"])
@pytest.mark.parametrize("restart", [False, True])
def test_suppression_removes_history_checkpoints_and_results(tmp_path, context, restart):
    client = SummaryClient()
    app = make_waku(tmp_path, client=client, context_policy=context, memory_policy="lifecycle", consolidate_every=10000)
    old = app.memory.facts.add("budget", "Keep the budget under 50")
    seed(app)
    app.memory.log_chat("Keep the budget under 50", "Confirmed")
    if context == "compact":
        assert "checkpoint 1" in app.compact().reply
    before = [tuple(r) for r in app.conn.execute("SELECT * FROM session_messages")]
    raw_checkpoints = [tuple(r) for r in app.conn.execute("SELECT * FROM session_checkpoints")]
    assert app.memory.facts.delete(old)
    assert app.checkpoints.latest("default") is None
    assert [tuple(r) for r in app.conn.execute("SELECT * FROM session_messages")] == before
    assert [tuple(r) for r in app.conn.execute("SELECT * FROM session_checkpoints")] == raw_checkpoints
    if restart:
        app.conn.close()
        app = make_waku(tmp_path, client=client, context_policy=context, memory_policy="legacy", consolidate_every=10000)
    client.requests.clear()
    assert app.respond("Continue the task").reply == "Answer"
    assert "budget under 50" not in encode(client.requests)
    assert "budget under 50" not in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert app.memory.session_history("default") == [("Continue the task", "Answer")]


def test_old_text_only_history_cannot_reenter_through_legacy_import(tmp_path):
    app = make_waku(tmp_path, client=SummaryClient(), context_policy="compact", memory_policy="lifecycle")
    app.memory.log_chat("Original forgotten sentence", "A paraphrase of that sentence")
    old = app.memory.facts.add("old", "Original forgotten sentence")
    app.memory.facts.delete(old)
    app.checkpoints.import_legacy("default")
    assert app.checkpoints.sources("default") == []
    assert app.conn.execute("SELECT count(*) FROM session_messages").fetchone()[0] == 2


def test_mutation_stops_remaining_tools_and_model_calls(tmp_path):
    client = SummaryClient()
    app = make_waku(tmp_path, client=client, memory_policy="lifecycle", consolidate_every=10000)
    old = app.memory.facts.add("old", "Old unique sentence")
    client.answers = [response([
        tool_block("manage_memory", {"action": "delete", "id": old}, "delete"),
        tool_block("save_note", {"subject": "old", "content": "Do not execute this"}, "later"),
    ], "tool_use")]
    result = app.respond("Forget the old fact")
    assert "memory" in result.reply.lower()
    assert len(result.tool_calls) == 1
    assert len(client.requests) == 2  # gate and first answer; no post-mutation answer
    assert app.conn.execute("SELECT count(*) FROM tool_executions").fetchone()[0] == 1
    assert app.checkpoints.sources("default") == []
    assert app.memory.facts.list() == []
    receipt = app.conn.execute("SELECT result_id FROM tool_executions").fetchone()[0]
    with pytest.raises(ValueError, match="suppression"):
        app.records.read("default", receipt, 0, 100)
    assert app.records.path(receipt).exists()


def test_live_legacy_instance_observes_another_connection_suppression(tmp_path):
    client = SummaryClient()
    first = make_waku(tmp_path, client=client, memory_policy="legacy", consolidate_every=10000)
    first.memory.log_chat("Stale old sentence", "Paraphrased old claim")
    first.session.switch("default")
    second = make_waku(tmp_path, client=SummaryClient(), memory_policy="lifecycle")
    old = second.memory.facts.add("old", "Stale old sentence")
    second.memory.facts.delete(old)
    first.respond("Continue")
    assert "Stale old sentence" not in encode(client.requests)
    assert "Paraphrased old claim" not in encode(client.requests)


def test_unknown_execution_remains_a_blocker_after_forgetting(tmp_path):
    client = SummaryClient()
    app = make_waku(tmp_path, client=client, memory_policy="lifecycle")
    turn = app.records.turn("default", "eval")
    turn.message("user", "An action")
    turn.begin("call-1", "send_message", {"content": "unknown"})
    old = app.memory.facts.add("old", "Forget this")
    app.memory.facts.delete(old)
    assert "unknown outcome" in app.respond("Continue").reply
    assert client.requests == []


def test_failed_export_preserves_suppression_and_requires_repair(tmp_path, monkeypatch):
    app = make_waku(tmp_path, client=SummaryClient(), memory_policy="lifecycle")
    old = app.memory.facts.add("old", "Old sentence")
    app.memory.export_markdown()

    def fail():
        raise OSError("disk full")

    monkeypatch.setattr(app.memory.lifecycle, "after_change", fail)
    with pytest.raises(TurnStopped, match="suppression was saved"):
        app.memory.facts.delete(old)
    assert app.memory.facts.list() == []
    assert app.conn.execute("SELECT export_dirty FROM memory_state").fetchone()[0] == 1
    app.memory.export_markdown()
    assert "Old sentence" not in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")


def test_protocol_fields_survive_redaction(tmp_path):
    app = make_waku(tmp_path, client=SummaryClient(), memory_policy="lifecycle")
    old = app.memory.facts.add("old", "assistant")
    app.memory.facts.delete(old)
    value = app.memory.lifecycle.clean_value({"role": "assistant", "content": "assistant"})
    assert value["role"] == "assistant"
    assert "withheld" in value["content"]
    block = app.memory.lifecycle.clean_value({"type": "tool_use", "id": "assistant", "name": "assistant",
                                             "input": {"name": "assistant"}})
    assert block["id"] == block["name"] == "assistant"
    assert "withheld" in block["input"]["name"]
    json.dumps(value)


def test_stale_summary_cannot_publish_after_suppression(tmp_path):
    client = SummaryClient()
    app = make_waku(tmp_path, client=client, memory_policy="lifecycle", context_policy="compact")
    seed(app)
    old = app.memory.facts.add("budget", "Keep the budget under 50")
    original = client.messages.create

    def during_call(**kwargs):
        result = original(**kwargs)
        app.memory.facts.delete(old)
        return result

    client.messages.create = during_call
    assert "stale response was discarded" in app.compact().reply
    assert app.conn.execute("SELECT count(*) FROM session_checkpoints").fetchone()[0] == 0


def test_new_checkpoint_after_suppression_advances_revision(tmp_path):
    app = make_waku(tmp_path, client=SummaryClient(), memory_policy="lifecycle", context_policy="compact")
    seed(app)
    assert "checkpoint 1" in app.compact().reply
    old = app.memory.facts.add("budget", "Keep the budget under 50")
    app.memory.facts.delete(old)
    for _ in range(8):
        app.respond("Start a new unrelated task")
    assert "checkpoint 2" in app.compact().reply
    latest = app.checkpoints.latest("default")
    assert latest["memory_generation"] == 1
    assert "budget under 50" not in latest["summary_json"]


def test_new_stale_result_cannot_leak_through_partial_pages(tmp_path):
    app = make_waku(tmp_path, client=SummaryClient(), memory_policy="lifecycle")
    old = app.memory.facts.add("old", "Forgotten unique sentence")
    app.memory.facts.delete(old)
    turn = app.records.turn("default", "eval")
    turn.message("user", "Read an external source")
    result_id = turn.begin("read-1", "read_fixture", {})
    original = "Prefix\nForgotten unique sentence\nSuffix"
    visible = turn.finish(result_id, original)
    assert "withheld" in visible
    with pytest.raises(ValueError, match="suppression"):
        app.records.read("default", result_id, 7, 3)
    assert app.records.path(result_id).read_text(encoding="utf-8") == original
