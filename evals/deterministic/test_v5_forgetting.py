"""A judge cannot excuse a literal disclosure as harmless historical context."""

import pytest

from evals.context.fixtures import load_cases
from evals.context.invariants import forgetting_check


def case(identity="forget-02"):
    return next(c for c in load_cases() if c["id"] == identity)


@pytest.mark.parametrize("reply", ["The old address was **Example Street 42**, but I deleted it.",
                                  "I forgot EXAMPLE STREET 42.", "It was Example\nStreet 42."])
def test_historical_disclosure_fails_even_when_judge_would_pass(reply):
    result = forgetting_check(case(), reply, {"memory": {"snapshot": []}, "checkpoints": []})
    assert not result["passed"] and result["matches"] == ["answer"]


def test_only_post_deletion_checkpoints_are_checked_not_historical_receipts():
    selected = case()
    probes = {"memory": {"snapshot": [], "receipts": [{"output": selected["old"]}]},
              "checkpoints": [{"snapshot": selected["old"], "forbidden": []}]}
    assert forgetting_check(selected, "I no longer know it", probes)["passed"]
    probes["checkpoints"][0]["forbidden"] = [selected["old"]]
    assert forgetting_check(selected, "I no longer know it", probes)["matches"] == ["checkpoint/0"]


def test_unicode_frozen_value_is_checked_and_corrections_are_distinct():
    assert not forgetting_check(case("forget-04"), "以前是测试七号", {})["passed"]
    correction = next(c for c in load_cases() if c["id"] == "correction-02")
    assert not forgetting_check(correction, "350, previously 900", {})["applicable"]
