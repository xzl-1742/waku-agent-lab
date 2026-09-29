"""Rejudging cannot replay tools, repair runtime failures or overwrite evidence."""

import copy

import pytest

from evals.context.rejudge import regrade
from evals.deterministic.test_v5_acceptance import report


def fixture():
    value = report(trials=1)
    value["runner"] = "live-exploratory"
    value["cases"] = value["cases"][:1]
    value["expected_runs"] = 1
    row = value["cases"][0]
    row.update(arm="A", action_check=True, task_success=None, replies=[{"reply": "done"}] * row["turns"],
               judge_input={"id": "blind", "task": "task", "evidence": [], "receipts": [], "reply": "done"})
    row["error_type"] = "JSONDecodeError"
    return value


def test_rejudge_repairs_scoring_only_and_retains_original(monkeypatch):
    from evals.context import quality, rejudge
    from evals.deterministic.test_v5_acceptance import verdict

    original = fixture()
    saved = copy.deepcopy(original)
    monkeypatch.setattr(rejudge, "grade", lambda *a: verdict())
    monkeypatch.setattr(quality, "grade", lambda *a: verdict())
    result = regrade(original, None, "offline")
    assert original == saved
    assert result["cases"][0]["status"] == "complete"
    assert result["cases"][0]["previous_judgment"]["error_type"] == "JSONDecodeError"
    assert result["runner"] == "live-rejudge" and result["quality_status"] == result["promotion_status"] == "incomplete"


def test_rejudge_cannot_fill_missing_runtime_or_old_evidence(monkeypatch):
    from evals.context import rejudge

    def forbidden(*args):
        raise AssertionError("No judge call allowed")
    monkeypatch.setattr(rejudge, "grade", forbidden)
    original = fixture()
    original["cases"][0]["replies"].pop()
    assert regrade(original, None, "offline")["cases"][0]["error_type"] == "JSONDecodeError"
    original["schema_version"] = 2
    with pytest.raises(ValueError, match="version-3"):
        regrade(original, None, "offline")
