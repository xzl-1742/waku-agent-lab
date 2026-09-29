"""The offline baseline proves state transitions; simulated answers are not quality scores."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from evals.context.fixtures import FIXTURES, expand, load_cases
from evals.context.measurement import RecordingClient, record_tools, source_snapshot
from evals.context.runner import run_case
from evals.helpers import response, text_block

CASES = load_cases()


def test_fixture_bank_is_frozen_before_candidate_tuning():
    # Changing this hash requires an explicitly versioned dataset revision.
    assert hashlib.sha256(FIXTURES.read_text(encoding="utf-8").encode()).hexdigest() == (
        "bab4c5fd9911bf3692681a1bd4725cade9c14018059a53910dd5427d03ceea1f"
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_scripted_scenario_persists_expected_outcomes(case, tmp_path):
    report = run_case(case, tmp_path / "home")
    assert report["status"] == "complete", report
    assert report["quality_status"] == "incomplete"
    assert report["task_success"] is None
    assert report["input_tokens"] is None
    assert report["cost_usd"] is None
    assert report["calls_by_stage"]["gate"] == case["turns"]
    assert report["calls_by_stage"]["consolidation"] == case["turns"] // 6
    assert len(report["turn_seconds"]) == case["turns"]
    assert len([s for s in expand(case) if s["op"] == "turn"]) == case["turns"]


def test_long_context_probe_detects_missing_constraint(tmp_path):
    case = next(c for c in CASES if c["id"] == "constraint-02")
    result = run_case(case, tmp_path / "home")
    assert result["status"] == "complete"
    assert not result["evidence_probes"]["current_fact_in_final_input"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_budget_configuration_completes_without_oversize_dispatch(case, tmp_path):
    result = run_case(case, tmp_path / "home", configuration="B")
    assert result["status"] == "complete", result
    assert result["quality_status"] == "incomplete"
    assert all(call["estimated_input_tokens"] + call["max_tokens"] + 1024 <= 32768
               for call in result["calls"])
    assert result["estimated_input_tokens_peak"] < 32768


def test_large_tool_scenario_reduces_estimated_input_without_extra_model_calls(tmp_path):
    case = next(c for c in CASES if c["id"] == "tool-03")
    a = run_case(case, tmp_path / "a", configuration="A")
    b = run_case(case, tmp_path / "b", configuration="B")
    assert a["status"] == b["status"] == "complete"
    assert a["model_calls"] == b["model_calls"]
    assert b["estimated_input_tokens_total"] < a["estimated_input_tokens_total"]
    assert b["estimated_input_tokens_peak"] < a["estimated_input_tokens_peak"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_compaction_configuration_preserves_sources_within_budget(case, tmp_path):
    result = run_case(case, tmp_path / "home", configuration="B2")
    assert result["status"] == "complete", result
    assert all(call["estimated_input_tokens"] + call["max_tokens"] + 1024 <= 32768 for call in result["calls"])
    if case["family"] in ("constraints", "tools", "isolation"):
        assert result["evidence_probes"]["current_fact_in_final_input"], result
    assert result["quality_status"] == "incomplete"
    assert result["cost_usd"] is None


def test_scripted_summary_uses_only_received_evidence():
    from evals.context.summary import summarize
    from waku.runtime.checkpoints import FIELDS

    payload = {"previous_summary": {field: [] for field in FIELDS},
               "sources": [{"source_id": 9, "role": "user", "text": '"Keep this constraint: port 1234"'}]}
    result = json.loads(summarize(payload))
    assert result["constraints"] == [{"text": "Keep this constraint: port 1234", "source_ids": [9]}]
    assert "9999" not in json.dumps(result)


@pytest.mark.parametrize("configuration", ["V3-window", "V3-compact"])
@pytest.mark.parametrize("family", ["corrections", "forgetting"])
def test_lifecycle_baselines_exclude_obsolete_facts(tmp_path, configuration, family):
    case = next(c for c in CASES if c["family"] == family)
    result = run_case(case, tmp_path / "home", configuration=configuration)
    assert result["status"] == "complete", result["errors"]
    assert not result["evidence_probes"]["obsolete_fact_in_final_input"]
    if family == "corrections":
        assert result["evidence_probes"]["current_fact_in_final_input"]
    assert result["quality_status"] == "incomplete"


def test_unknown_fixture_schema_and_family_fail_loudly(tmp_path):
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    path = tmp_path / "cases.json"
    data["schema_version"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        load_cases(path)
    data["schema_version"] = 1
    data["cases"][0]["family"] = "typo"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="family"):
        load_cases(path)


def test_call_timing_wraps_execution_and_preserves_missing_usage():
    now = [10.0]

    def create(**kwargs):
        now[0] += 2.75
        return SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=12))

    client = RecordingClient(SimpleNamespace(messages=SimpleNamespace(create=create)),
                             clock=lambda: now[0])
    client.messages.create(system="test", messages=[])
    call = client.calls[0]
    assert call["duration_seconds"] == 2.75
    assert call["input_tokens"] == 12
    assert call["output_tokens"] is None
    assert call["usage_source"] == "unmeasured"


def test_failed_calls_are_still_counted_and_timed():
    times = iter([1.0, 3.0])

    def fail(**kwargs):
        raise RuntimeError("synthetic failure")

    client = RecordingClient(SimpleNamespace(messages=SimpleNamespace(create=fail)),
                             clock=lambda: next(times))
    with pytest.raises(RuntimeError):
        client.messages.create(system="test", messages=[])
    assert client.calls[0]["status"] == "failed"
    assert client.calls[0]["duration_seconds"] == 2


def test_synthetic_zero_usage_does_not_become_real_zero_cost():
    client = RecordingClient(SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kw: response([text_block("synthetic")]))), synthetic=True)
    client.messages.create(system="test", messages=[])
    assert client.calls[0]["input_tokens"] is None
    assert client.calls[0]["output_tokens"] is None
    assert client.calls[0]["usage_source"] == "synthetic"


def test_tool_timing_wraps_real_execution():
    now = [1.0]
    calls = []

    def execute(*args, **kwargs):
        now[0] += 3
        return "ok"

    registry = SimpleNamespace(execute=execute)
    record_tools(registry, calls, clock=lambda: now[0])
    assert registry.execute("fixture", {}) == "ok"
    assert calls == [{"tool": "fixture", "status": "complete", "output_bytes": 2,
                      "duration_seconds": 3}]


def test_source_manifest_works_without_git_and_excludes_user_files(tmp_path):
    (tmp_path / "waku").mkdir()
    (tmp_path / "waku" / "sample.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SYNTHETIC=never-hash-this\n", encoding="utf-8")
    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "note.py").write_text("private", encoding="utf-8")
    snapshot = source_snapshot(tmp_path)
    assert snapshot["commit"] is None
    assert list(snapshot["files"]) == ["waku/sample.py"]
