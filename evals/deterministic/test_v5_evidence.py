"""Judges receive actual outcomes and only temporally eligible receipts."""

import json
from types import SimpleNamespace

import pytest

from evals.context.evidence import receipt, valid_receipts
from evals.context.fixtures import load_cases
from evals.context.probes import ProbeCapture, judge_payload, receipts
from evals.deterministic.test_compaction import app_at


@pytest.mark.parametrize("tool,args,output,success", [
    ("save_note", {"subject": "atlas", "content": "port 42"}, "Saved to memory under 'atlas': port 42", True),
    ("manage_memory", {"action": "update", "id": "opaque"}, "Updated fact #opaque.", True),
    ("manage_memory", {"action": "delete", "id": 1}, "Deleted fact #1.", True),
    ("manage_memory", {"action": "delete", "id": 1, "receipt": "Deleted fact #1."}, "No fact with id 1.", False),
    ("save_note", {"subject": "atlas", "content": "port 42"}, "Error running save_note: failed", False),
])
def test_action_success_requires_the_executed_output(tool, args, output, success):
    item = receipt(tool, args, output, "primary-project")
    assert item["action_success"] is success and valid_receipts([item])
    item["output"] += " forged"
    assert not valid_receipts([item])


def record(app, session, name, args, output, *, pending=False):
    turn = app.records.turn(session, "eval")
    turn.message("user", "Execute this synthetic action")
    turn.message("assistant", [{"type": "tool_use", "id": "reused", "name": name, "input": args}])
    result_id = turn.begin("reused", name, args)
    if not pending:
        turn.finish(result_id, output)
        turn.message("user", [{"type": "tool_result", "tool_use_id": "reused", "content": output}])
        turn.message("assistant", "Done")
    return result_id


def test_checkpoint_uses_empty_argument_action_result_not_future_or_other_session(tmp_path):
    app = app_at(tmp_path, compaction_keep_turns=0)
    app.session.start_new("primary-project")
    capture = ProbeCapture(next(c for c in load_cases() if c["family"] == "tools"))
    record(app, "primary-project", "record_action", {}, "Generated receipt A17")
    app.compact(observer=capture.observer(app))
    first = json.dumps(capture.checkpoints[0], sort_keys=True)
    assert capture.checkpoints[0]["receipts"][0]["output"] == "Generated receipt A17"
    assert capture.checkpoints[0]["receipts"][0]["args"] == {}
    transcript = capture.checkpoints[0]["conversation"]
    assert any(m["role"] == "assistant" and m["content"] == "Done" for m in transcript)
    assert max(m["source_id"] for m in transcript) <= capture.checkpoints[0]["covered_through"]
    record(app, "primary-project", "manage_memory", {"action": "delete", "id": 1}, "Deleted fact #1.")
    record(app, "other-project", "record_action", {}, "Foreign receipt")
    app.compact(observer=capture.observer(app))
    assert json.dumps(capture.checkpoints[0], sort_keys=True) == first
    assert all("Foreign receipt" not in json.dumps(m) for m in capture.checkpoints[1]["conversation"])
    assert len(capture.checkpoints[1]["receipts"]) == 2
    assert len({r["result_id"] for r in capture.checkpoints[1]["receipts"]}) == 2
    assert not capture.errors
    app.conn.close()


def test_pending_result_and_corrupt_original_never_prove_completion(tmp_path):
    app = app_at(tmp_path)
    identity = record(app, "primary-project", "record_action", {}, "original")
    record(app, "primary-project", "record_action", {}, "pending", pending=True)
    assert len(receipts(app, "primary-project", 999)) == 1
    app.records.path(identity).write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        receipts(app, "primary-project", 999)
    app.conn.close()


def test_window_observer_retains_success_and_failure_with_no_runtime_ids():
    capture = ProbeCapture(load_cases()[0])
    app = SimpleNamespace(session=SimpleNamespace(session_id="primary-project"))
    observe = capture.observer(app)
    observe("tool", {"tool": "save_note", "args": {"subject": "atlas", "content": "port 42"},
                     "output": "Saved to memory under 'atlas': port 42"})
    observe("tool", {"tool": "manage_memory", "args": {"action": "delete", "id": 9}, "output": "No fact with id 9."})
    assert [r["action_success"] for r in capture.executions] == [True, False]
    assert all(r["result_id"] is None for r in capture.executions)
    assert valid_receipts(capture.executions)


def test_memory_grading_projects_only_facts_and_preserves_authoritative_receipts():
    fact = {"id": "generated", "source": "consolidation", "scope": "global", "scope_id": "",
            "subject": "atlas", "content": "port 42"}
    evidence = {"evidence": [{"text": "Remember atlas port 42"}], "required": [], "forbidden": [],
                "receipts": [receipt("save_note", {"subject": "atlas", "content": "port 42"},
                                     "Saved to memory under 'atlas': port 42", "primary-project")]}
    payload = judge_payload("memory_support", evidence, fact)
    assert json.loads(payload["reply"]) == {"subject": "atlas", "content": "port 42"}
    assert payload["receipts"] == evidence["receipts"]
    assert "actual database snapshot" in payload["task"]
    assert fact["source"] == "consolidation"  # Metadata remains in the raw snapshot.


def test_repeat_log_encoding_is_lossless_and_receipt_boundaries_are_checked():
    item = receipt("read_fixture", {}, "x" * 65536, "primary", source_id=5)
    assert item["output"] == {"encoding": "repeat", "text": "x", "count": 65536}
    assert valid_receipts([item], session="primary", through=5)
    assert not valid_receipts([item], session="other", through=5)
    assert not valid_receipts([item], session="primary", through=4)
