"""A display summary cannot overrule failed or missing raw evaluation evidence."""

import copy
import json
from pathlib import Path

import pytest

from evals.context.acceptance import calibrated, decide, validate_rows
from evals.context.experiment import manifest
from evals.context.fixtures import expand, load_cases
from evals.context.measurement import digest
from evals.context.probes import checks, expectations
from evals.context.quality import RUBRIC, promotion, second_provider_status


def verdict(success=True, **kwargs):
    return {"task_success": success, "stale_assertion": False, "unsupported_assertion": False,
            "reason": "Synthetic acceptance test", **kwargs}


def evidence(case):
    session, messages = "primary-project", []
    for step in expand(case):
        if step["op"] in ("switch", "restart"):
            session = step["session"]
        else:
            messages.append({"session_id": session, "text": step["message"]})
    expected = expectations(case, messages, memory=True)
    probes = {"schema_version": 1, "events": [], "persisted": [], "checkpoints": [], "capture_errors": [], "checks": [],
              "memory": {"snapshot": [{"id": 1, "subject": case["subject"], "content": case["current"], "source": "user"}]
                         if expected["required"] else [], "evidence": messages, "receipts": [], **expected}}
    probes["checks"] = [{"id": key, "kind": kind, "source": source, "verdict": verdict(), "error_type": None}
                        for key, kind, _, _, source in checks(probes)]
    return probes


def report(provider="primary", trials=5, reserved=False):
    cases = [c for c in load_cases() if not reserved or c["split"] == "reserved"]
    rows = []
    for case in cases:
        for arm in "ABCD":
            for trial in range(1, trials + 1):
                rows.append({"id": case["id"], "family": case["family"], "turns": case["turns"], "trial": trial,
                    "configuration": f"V5-{arm}", "status": "complete", "error_type": None,
                    "verdict": verdict(), "actual_actions": [case["old"]] if case["family"] == "tools" else [],
                    "turn_seconds": [1.0] * case["turns"], "probes": evidence(case),
                    "usage": {"runtime": {"calls": case["turns"], "usage_complete": True,
                                          "input_tokens": 1000 if arm == "A" else 500, "output_tokens": 100}}})
    labels = json.loads((Path(__file__).parents[1] / "context" / "calibration.example.json").read_text())
    calibration = {"status": "complete", "reviewer": "offline fixture only", "labels_sha256": digest(labels),
                   "model": "synthetic", "rubric": RUBRIC, "results": [
                       {"id": c["id"], "kind": c.get("kind", "answer"), "expected": c["expected"],
                        "verdict": {**c["expected"], "reason": "Synthetic test"}} for c in labels["cases"]]}
    source = {"manifest_sha256": "synthetic-source-fixture"}
    result = {"schema_version": 2, "runner": "live", "provider": provider, "status": "complete", "quality_status": "complete",
              "source_stable": True, "source": source, "source_end": dict(source), "manifest_sha256": digest(manifest()),
              "trials": trials, "cases": rows, "calibration": calibration}
    if not reserved:
        result["second_provider_evidence"] = report("secondary", 1, True)
    return result


@pytest.fixture
def complete_report():
    return report()


def test_valid_raw_evidence_promotes_without_display_totals(complete_report):
    assert promotion(complete_report) == "complete"


@pytest.mark.parametrize("mutation,expected", [("stale", "failed"), ("action", "failed"), ("task", "failed"),
                                               ("error", "incomplete"), ("empty", "incomplete"), ("probe", "incomplete")])
def test_display_summary_cannot_conceal_bad_raw_rows(complete_report, mutation, expected):
    row = next(r for r in complete_report["cases"] if r["family"] == "forgetting" and r["configuration"] == "V5-D")
    complete_report["summary"] = {"coverage_complete": True, "arms": {"D": {"critical_failures": []}}}
    complete_report["quality_metrics"] = {"long_task_gain_lower_95": 1, "critical_failures": 0}
    if mutation == "stale":
        row["verdict"]["stale_assertion"] = True
    elif mutation == "action":
        row["actual_actions"] = ["unexpected duplicate action"]
    elif mutation == "task":
        row["verdict"]["task_success"] = False
    elif mutation == "error":
        row["error_type"] = "Interrupted"
    elif mutation == "empty":
        row["verdict"] = {}
    else:
        row["probes"] = None
    assert promotion(complete_report) == expected


def test_second_provider_requires_successful_tasks_and_raw_calibration():
    secondary = report("secondary", 1, True)
    assert second_provider_status(secondary, "primary")["status"] == "complete"
    for row in secondary["cases"]:
        row["verdict"]["task_success"] = False
    assert second_provider_status(secondary, "primary")["status"] == "incomplete"


def test_mutated_calibration_and_source_snapshots_cannot_pass(complete_report):
    assert calibrated(complete_report["calibration"])
    copied = copy.deepcopy(complete_report["calibration"])
    copied["results"][1]["verdict"]["stale_assertion"] = False
    assert not calibrated(copied)
    complete_report["source_end"]["manifest_sha256"] = "changed"
    assert promotion(complete_report) == "incomplete"


def test_timing_and_memory_evidence_must_cover_the_frozen_run(complete_report):
    row = complete_report["cases"][0]
    saved = row["turn_seconds"]
    row["turn_seconds"] = [1]
    assert validate_rows(complete_report) is None
    row["turn_seconds"] = saved
    row["probes"]["memory"]["evidence"].pop()
    assert validate_rows(complete_report) is None


def test_quality_gain_does_not_require_alternative_token_savings():
    values = {"long_task_gain_lower_95": .15, "short_task_change_lower_95": 0,
              "short_latency_ratio_upper_95": 1, "critical_failures": 0,
              "runtime_reduction_lower_95": None, "baseline_long_success": .5}
    assert decide(values) == "complete"
    values["long_task_gain_lower_95"] = 0
    values["baseline_long_success"] = 1
    assert decide(values) == "incomplete"


def test_reserved_regression_cannot_be_hidden_by_development_success(complete_report):
    reserved = {c["id"] for c in load_cases() if c["split"] == "reserved"}
    for row in complete_report["cases"]:
        if row["turns"] == 8 and row["id"] in reserved and row["family"] in ("constraints", "retrieval") and row["configuration"] == "V5-D":
            row["verdict"]["task_success"] = False
    assert promotion(complete_report) == "failed"
