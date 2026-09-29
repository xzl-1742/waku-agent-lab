"""Intermediate evaluation observes real state and never invents coverage."""

import json
from types import SimpleNamespace

import pytest

from evals.context.fixtures import expand, load_cases
from evals.context.probes import ProbeCapture, checks, expectations, grade_probes, metrics, probe_status
from evals.deterministic.test_compaction import app_at


def messages(case, count=None):
    return [{"session_id": "primary-project", "text": s["message"]}
            for s in expand(case) if s["op"] == "turn"][:count]


@pytest.mark.parametrize("family", ["corrections", "forgetting"])
def test_probe_expectations_do_not_apply_future_corrections(family):
    case = next(c for c in load_cases() if c["family"] == family)
    before = expectations(case, messages(case, case["position"]))
    early = expectations(case, messages(case, case["position"] + 1))
    changed = expectations(case, messages(case, case["position"] + 3))
    assert before == {"required": [], "forbidden": []}
    assert early["required"] == [f'{case["subject"]}: {case["old"]}'] and not early["forbidden"]
    assert changed["forbidden"] == [case["old"]]
    assert changed["required"] == ([f'{case["subject"]}: {case["current"]}'] if family == "corrections" else [])


def test_capture_preserves_each_published_revision_and_covered_evidence(tmp_path):
    case = next(c for c in load_cases() if c["family"] == "constraints")
    capture = ProbeCapture(case)
    app = app_at(tmp_path, compaction_keep_turns=0)
    app.session.start_new("primary-project")
    text = next(s["message"] for s in expand(case) if s["op"] == "turn" and case["old"] in s["message"])
    turn = app.records.turn("primary-project", "eval")
    turn.message("user", text)
    turn.message("assistant", "Noted")
    app.compact(observer=capture.observer(app))
    first = json.dumps(capture.checkpoints[0], sort_keys=True)
    turn = app.records.turn("primary-project", "eval")
    turn.message("user", "Later detail must not enter the first snapshot")
    turn.message("assistant", "Noted")
    app.compact(observer=capture.observer(app))
    assert [c["revision"] for c in capture.checkpoints] == [1, 2]
    assert json.dumps(capture.checkpoints[0], sort_keys=True) == first
    assert "Later detail" not in first
    assert capture.checkpoints[0]["required"] == [f'{case["subject"]}: {case["old"]}']
    app.conn.close()


def test_observer_failure_is_incomplete_without_interrupting_runtime():
    capture = ProbeCapture(load_cases()[0])
    capture.observer(SimpleNamespace(conn=None))("compaction_completed", {"session_id": "one", "revision": 1, "covered_through": 2})
    assert len(capture.events) == 1 and len(capture.errors) == 1
    assert probe_status(capture.report()) == "incomplete"


def test_final_memory_checks_current_facts_and_consolidation_separately(tmp_path, monkeypatch):
    from evals.context import quality

    case = next(c for c in load_cases() if c["family"] == "corrections")
    capture = ProbeCapture(case)
    capture.inputs = messages(case)
    app = app_at(tmp_path)
    app.memory.facts.add(case["subject"], case["old"], source="consolidation")
    capture.finish(app, [])
    app.conn.close()
    probes = capture.report()
    assert len(checks(probes)) == 2
    def judge(client, model, item):
        assert "configuration" not in item and "expected" not in item
        return {"task_success": False, "stale_assertion": "stored fact:" in item["task"],
                "unsupported_assertion": False, "reason": "Stored value is obsolete or current value missing"}
    monkeypatch.setattr(quality, "grade", judge)
    grade_probes(probes, None, "offline")
    assert probe_status(probes) == "failed"
    assert metrics(probes)["consolidated_fact_supportedness"]["rate"] == 0
    assert metrics(probes)["required_fact_recall"]["rate"] == 0
    probes["checks"].pop()
    assert probe_status(probes) == "incomplete"


def test_empty_store_recall_and_zero_denominators_are_distinct(tmp_path, monkeypatch):
    from evals.context import quality

    case = next(c for c in load_cases() if c["family"] == "retrieval")
    capture = ProbeCapture(case)
    capture.inputs = messages(case)
    app = app_at(tmp_path)
    capture.finish(app, [])
    app.conn.close()
    probes = capture.report()
    monkeypatch.setattr(quality, "grade", lambda *args: {"task_success": False, "stale_assertion": False,
                                                       "unsupported_assertion": False, "reason": "Required memory absent"})
    grade_probes(probes, None, "offline")
    result = metrics(probes)
    assert result["status"] == "failed"
    assert result["memory_supportedness"]["rate"] is None
    assert result["required_fact_recall"]["rate"] == 0


def test_bounded_snapshot_cannot_silently_drop_facts():
    capture = ProbeCapture(load_cases()[0])
    app = SimpleNamespace(memory=SimpleNamespace(facts=SimpleNamespace(list=lambda limit: [{}] * limit)))
    capture.finish(app, [])
    assert capture.memory is None and capture.errors
    assert probe_status(capture.report()) == "incomplete"
