"""The V4 report measures real retrieval without pretending scripts are quality."""

import pytest

from evals.retrieval.runner import load_cases, report, run_case


def test_fixture_bank_keeps_development_and_reserved_categories():
    cases = load_cases()["cases"]
    for category in {c["category"] for c in cases}:
        assert len([c for c in cases if c["category"] == category and c["split"] == "development"]) == 2
        assert len([c for c in cases if c["category"] == category and c["split"] == "reserved"]) == 1


@pytest.mark.parametrize("case", [c for c in load_cases()["cases"] if c["split"] == "development"], ids=lambda c: c["id"])
def test_development_scenarios_preserve_critical_retrieval_limits(tmp_path, case):
    result = run_case(case, tmp_path / "home", "selective")
    assert result["status"] == "complete", result
    assert result["forbidden_evidence"] == []
    assert not result["budget_exceeded"]
    assert result["unsupported_assertions"] is None


def test_report_exposes_paraphrase_miss_and_unmeasured_quality(tmp_path):
    cases = [c for c in load_cases()["cases"] if c["id"] in ("cjk-1", "para-1", "pronoun-2")]
    result = report(cases, tmp_path)
    assert result["quality_status"] == "incomplete"
    assert result["cost_usd"] is None
    by_id = {r["id"]: r for r in result["cases"] if r["policy"] == "V4-retrieval-candidate"}
    assert by_id["cjk-1"]["delivered_recall_at_k"] == 1
    assert by_id["para-1"]["search_recall_at_k"] == 0
    assert by_id["pronoun-2"]["gate_false_negative"]
    assert by_id["pronoun-2"]["post_recovery_recall_at_k"] == 1
