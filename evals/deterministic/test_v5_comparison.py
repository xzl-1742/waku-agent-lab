"""The V5 matrix must not turn scripted execution into a quality claim."""

import pytest

from evals.context.comparison import paired_interval, summarize
from evals.context.experiment import manifest, policies
from evals.context.fixtures import load_cases
from evals.context.quality import blind, calibrate, promotion, validate
from evals.context.runner import run_case


def test_historical_and_v5_labels_do_not_drift():
    assert policies("B")["context_policy"] == "budget"
    assert policies("V5-B")["context_policy"] == "compact"
    assert policies("V5-D")["retrieval_policy"] == "selective"
    assert manifest()["critical_families"] == ["corrections", "forgetting", "isolation", "tools"]


@pytest.mark.parametrize("arm", ["V5-C", "V5-D"])
@pytest.mark.parametrize("family", ["constraints", "tools", "corrections", "forgetting", "retrieval", "isolation"])
def test_combined_policies_complete_short_scenarios(tmp_path, arm, family):
    case = next(c for c in load_cases() if c["family"] == family and c["turns"] == 8)
    result = run_case(case, tmp_path / "home", arm)
    assert result["status"] == "complete", result["errors"] or result["outcome_checks"]
    assert result["calls_by_stage"]["selective_gate"] == 8
    assert result["task_success"] is None and result["usage"]["runtime"]["input_tokens"] is None
    assert len(result["replies"]) == 8


def test_paired_cluster_interval_keeps_repetitions_together():
    rows = [{"id": key, "family": "f", "trial": trial, "configuration": arm, "score": value}
            for key, delta in (("one", 2), ("two", 4)) for trial in range(1, 6)
            for arm, value in (("A", 10), ("D", 10 + delta))]
    result = paired_interval(rows, "D", "A", "score")
    assert result["delta"] == 3 and result["paired_scenarios"] == 2
    assert result["interval_95"] == [2, 4]
    assert paired_interval(rows, "D", "A", "missing")["delta"] is None


def test_matrix_rejects_missing_coverage():
    result = summarize([], [("case", "V5-D", 1)], manifest())
    assert not result["coverage_complete"]


def test_resource_intervals_use_declared_median_without_dropping_tail():
    rows = [{"id": key, "family": "f", "trial": 1, "configuration": arm, "score": score}
            for key, value in (("one", 1), ("two", 2), ("tail", 100))
            for arm, score in (("A", 0), ("D", value))]
    result = paired_interval(rows, "D", "A", "score", statistic="median")
    assert result["delta"] == 2 and result["interval_95"] == [1, 100]
    assert result["statistic"] == "median"


def test_blind_judge_payload_omits_arm_model_and_expected_labels():
    item = {"id": "D-case", "configuration": "D", "model": "candidate", "expected": {"task_success": True},
            "task": "remember", "evidence": ["current fact"], "reply": "answer", "receipts": []}
    blinded, mapping = blind([item], 1)
    assert set(blinded[0]) == {"id", "task", "evidence", "reply", "receipts"}
    assert blinded[0]["id"] != item["id"] and mapping[blinded[0]["id"]] == item["id"]


def test_unreviewed_calibration_never_calls_model():
    assert calibrate(None, "test", [{"id": "example"}])["status"] == "incomplete"


@pytest.mark.parametrize("value", ['{}', '{"task_success":true,"stale_assertion":false,"unsupported_assertion":"false","reason":"ok"}'])
def test_judge_schema_rejects_invalid_labels(value):
    with pytest.raises(ValueError):
        validate(value)


def test_scripted_and_missing_quality_never_promote():
    assert promotion({"status": "complete", "quality_status": "incomplete"}) == "incomplete"
    assert promotion({"status": "failed"}) == "failed"
    assert promotion({"summary": {"arms": {"D": {"critical_failures": ["forgotten"]}}}}) == "failed"


def test_gate_history_and_latest_share_comparison_status(tmp_path):
    import json

    from waku.ops.release_gate import report

    suites = {k: {"status": "complete"} for k in ("deterministic", "judge")}
    record = report(suites, tmp_path, {"status": "incomplete"})
    assert record["status"] == "incomplete"
    assert json.loads((tmp_path / "eval_runs.jsonl").read_text())["status"] == "incomplete"
    suites["deterministic"]["status"] = "failed"
    assert report(suites, tmp_path, {"status": "incomplete"})["status"] == "failed"
