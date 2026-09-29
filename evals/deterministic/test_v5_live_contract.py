"""Explicit live/experimental paths cannot silently fabricate quality evidence."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from evals.context.live import execute, plan
from evals.context.quality import aggregate, calibrate
from evals.helpers import ScriptedClient, response, text_block
from evals.retrieval.hybrid import cosine, fusion, report


def test_live_plan_imports_no_configuration_or_credentials():
    result = subprocess.run([sys.executable, "-c", "from evals.context.live import plan; import sys; assert 'waku.config' not in sys.modules; print(plan('all')['scenario_runs'])"],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "720"
    assert not plan()["credentials_loaded"]
    with pytest.raises(ValueError, match="explicit"):
        execute(SimpleNamespace(live=False))


def test_critical_calibration_error_cannot_hide_in_average():
    examples = [{"id": str(i), "task": "task", "evidence": [], "reply": "reply", "receipts": [],
                 "expected": {"task_success": True, "stale_assertion": i == 0, "unsupported_assertion": i == 1}} for i in range(20)]
    reply = json.dumps({"task_success": True, "stale_assertion": False, "unsupported_assertion": False, "reason": "synthetic"})
    client = ScriptedClient([response([text_block(reply)]) for _ in examples])
    assert calibrate(client, "test", examples, reviewed=True)["status"] == "failed"


def test_hybrid_experiment_filters_before_fusion_and_requires_provenance():
    assert fusion(["active"], ["forgotten", "active"], {"active"}) == ["active"]
    assert cosine([1, 0], [1, 0]) == 1
    with pytest.raises(ValueError):
        cosine([float("nan")], [1])
    assert report()["status"] == "unavailable"
    with pytest.raises(ValueError, match="provenance"):
        report({"cases": {}})


def test_live_aggregation_does_not_replace_unknown_tokens_with_estimates():
    rows = [{"id": "one", "trial": 1, "configuration": arm, "turns": 32, "family": "constraints",
             "status": "complete", "task_success": True, "action_check": True,
             "verdict": {"stale_assertion": False, "unsupported_assertion": False}, "turn_seconds": [1, 2],
             "usage": {"runtime": {"usage_complete": False, "input_tokens": None, "output_tokens": None}}}
            for arm in ("V5-A", "V5-D")]
    result = aggregate(rows, [("one", r["configuration"], 1) for r in rows])
    assert result["summary"]["coverage_complete"]
    assert result["quality_metrics"]["long_task_gain_lower_95"] == 0
    assert result["quality_metrics"]["runtime_reduction_lower_95"] is None


@pytest.mark.parametrize("mode", ["complete", "allowance", "startup", "stale_memory", "action", "exploratory", "stop"])
def test_explicit_live_entry_runs_only_synthetic_local_tools_when_injected(tmp_path, monkeypatch, mode):
    import dotenv
    import dotenv.main

    from evals.context import live, quality
    from evals.helpers import tool_block
    from waku.app import Waku
    from waku.loop import models

    # Restore discovery hooks after testing the live-entry bootstrap.
    for module in (dotenv, dotenv.main):
        monkeypatch.setattr(module, "load_dotenv", module.load_dotenv)
        monkeypatch.setattr(module, "find_dotenv", module.find_dotenv)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-offline-placeholder")
    case = {"id": "synthetic", "family": "constraints", "split": "development", "turns": 8,
            "position": 0, "output_kib": 1, "subject": "project", "old": "limit 10", "current": "limit 10", "question": "What limit?"}
    if mode == "stale_memory":
        case.update(family="corrections", current="limit 20")
    elif mode == "action":
        case.update(family="tools", old="local-generated-receipt")
    monkeypatch.setattr(live, "load_cases", lambda: [case])
    monkeypatch.setattr(live, "manifest", lambda: {"experiment": "context-memory-v5", "seed": 1, "capacity": 32768,
        "arms": {"A": {"context_policy": "window", "memory_policy": "legacy", "retrieval_policy": "legacy"}}})
    monkeypatch.setattr(live, "expand", lambda case: [{"op": "turn", "message": "What limit?"}])
    if mode != "exploratory":
        monkeypatch.setattr(quality, "calibrate", lambda *a, **k: {"status": "complete", "agreement": 1})
    def grade(client, model, item):
        bad = mode == "stale_memory" and "stored fact:" in item["task"]
        return {"task_success": not bad, "stale_assertion": bad, "unsupported_assertion": False, "reason": "Offline test"}
    monkeypatch.setattr(quality, "grade", grade)
    def get_client(settings):
        script = [response([text_block('{"retrieve":false,"query":"","reason":"general"}')])]
        if mode == "action":
            script.append(response([tool_block("record_action", {})]))
        script.append(response([text_block("limit 10")]))
        return ScriptedClient(script)
    monkeypatch.setattr(models, "get_client", get_client)
    if mode in ("startup", "stale_memory"):
        original = Waku.__init__
        def initialize(self, *a, **k):
            if mode == "startup":
                raise RuntimeError("Synthetic startup failure")
            original(self, *a, **k)
            self.memory.facts.add("project", "limit 10", source="consolidation")
        monkeypatch.setattr(Waku, "__init__", initialize)
    labels = tmp_path / "calibration.json"
    labels.write_text(json.dumps({"reviewed": mode != "exploratory", "reviewer": "synthetic test", "cases": [{"id": "test"}]}))
    result = execute(SimpleNamespace(live=True, provider="anthropic", model="scripted-main", small_model="scripted-small",
        judge_model="scripted-judge", calibration=labels, output=tmp_path / "result", split="development", trials=1,
        max_calls=2 if mode == "allowance" else 10, exploratory=mode == "exploratory", case_ids=["synthetic"]),
        should_stop=lambda: mode == "stop")
    if mode == "stop":
        assert result["actual_runs"] == 0 and result["expected_runs"] == 1
        assert result["status"] == result["promotion_status"] == "incomplete"
        return
    assert result["actual_runs"] == 1
    row = result["cases"][0]
    assert json.loads((tmp_path / "result" / "report.json").read_text())["status"] == result["status"]
    if mode in ("allowance", "startup"):
        assert result["status"] == result["quality_status"] == "incomplete"
        assert row["error_type"] and row["task_success"] is None
    else:
        assert result["status"] == "complete" and row["replies"][0]["reply"] == "limit 10"
        assert result["usage"]["runtime"]["calls"] == (3 if mode == "action" else 2)
        if mode == "stale_memory":
            assert row["verdict"]["task_success"] and row["task_success"] is False
            assert row["probe_metrics"]["consolidated_fact_supportedness"]["rate"] == 0
        elif mode == "action":
            assert row["actual_actions"] == ["local-generated-receipt"] and row["action_check"]
    assert result["promotion_status"] == "incomplete"
    if mode == "exploratory":
        assert result["runner"] == "live-exploratory"
        assert result["calibration"]["status"] == result["quality_status"] == "incomplete"


def test_live_price_artifacts_require_dated_provenance_and_valid_numbers(tmp_path):
    from waku.ops.usage import load_rates, summarize

    path = tmp_path / "rates.json"
    rate = {"provider": "synthetic", "model": "main", "source": "offline test fixture",
            "checked_at": "2026-09-29", "input": 1, "output": 2, "cached_input": .1}
    path.write_text(json.dumps([rate]))
    usage = summarize([{"provider": "synthetic", "model": "main", "in": 1000, "out": 100,
                        "cache_included_in_input": True, "cache_read_input_tokens": 500}], load_rates(path))
    assert usage["runtime"]["cost_usd"] == pytest.approx(.00075)
    path.write_text(json.dumps([{**rate, "input": float("nan")}]))
    with pytest.raises(ValueError):
        load_rates(path)
    path.write_text(json.dumps([{**rate, "checked_at": ""}]))
    with pytest.raises(ValueError):
        load_rates(path)


def test_partial_live_reports_and_same_provider_cannot_supply_release_evidence():
    from evals.context.experiment import manifest
    from evals.context.measurement import digest
    from evals.context.quality import frozen_coverage, promotion, second_provider_status

    report = {"runner": "live", "status": "complete", "quality_status": "complete", "source_stable": True,
              "manifest_sha256": digest(manifest()), "provider": "primary", "trials": 5,
              "summary": {"coverage_complete": True}, "calibration": {"status": "complete"},
              "second_provider": {"status": "complete"}, "cases": []}
    assert not frozen_coverage(report)
    assert promotion(report) == "incomplete"
    assert second_provider_status(report, "primary")["status"] == "incomplete"


def test_calibration_rejects_empty_expected_labels_before_calling_judge():
    assert calibrate(None, "test", [{"id": "empty", "expected": {}}], reviewed=True)["status"] == "failed"
