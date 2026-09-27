"""Missing quality evidence must never turn into a green release gate."""

import json

import pytest

from waku.ops import release_gate as gate


def complete(**extra):
    return {"status": "complete", "passed": 3, "failed": 0, "errors": 0,
            "skipped": 0, **extra}


@pytest.mark.parametrize("judge", [None, gate.skipped("no key"), complete(skipped=2)])
def test_missing_or_partial_live_evidence_is_incomplete(judge):
    suites = {"deterministic": complete()}
    if judge is not None:
        suites["judge"] = judge
    assert gate.verdict(suites) == "incomplete"


@pytest.mark.parametrize(("xml", "code", "status"), [
    ("<testcase/>", 0, "complete"),
    ("<testcase><skipped/></testcase>", 0, "skipped"),
    ("", 5, "skipped"),
    ("<testcase><error/></testcase>", 2, "failed"),
    ("<testcase><failure/></testcase>", 1, "failed"),
])
def test_pytest_coverage(xml, code, status, tmp_path):
    path = tmp_path / "result.xml"
    path.write_text(f"<testsuites><testsuite>{xml}</testsuite></testsuites>", encoding="utf-8")
    result = gate.read_result(path, code, 1.25)
    assert result["status"] == status
    assert result["duration_seconds"] == 1.25


def test_strict_gate_without_live_run_is_closed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate, "run", lambda suite: complete())
    assert gate.main(["--strict", "--output", str(tmp_path)]) == 2
    assert "GATE OPEN" not in capsys.readouterr().out
    assert json.loads((tmp_path / "eval_report.json").read_text())["status"] == "incomplete"
    assert gate.main(["--output", str(tmp_path)]) == 0


def test_live_without_credentials_is_skipped(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(gate, "run", lambda suite: calls.append(suite) or complete())
    assert gate.main(["--strict", "--live", "--output", str(tmp_path)]) == 2
    assert calls == ["deterministic"]
    result = json.loads((tmp_path / "eval_report.json").read_text())
    assert "no credentials" in result["suites"]["judge"]["reason"]


def test_complete_required_suites_open_gate():
    assert gate.verdict({"deterministic": complete(), "judge": complete()}) == "complete"


def test_live_gate_accepts_active_provider_key(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("WAKU_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key-never-sent")
    monkeypatch.setattr(gate, "run", lambda suite: calls.append(suite) or complete())
    assert gate.main(["--strict", "--live", "--output", str(tmp_path)]) == 0
    assert calls == ["deterministic", "judge"]


def test_unrelated_provider_key_cannot_enable_live_suite(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("WAKU_PROVIDER", "anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key-never-sent")
    monkeypatch.setattr(gate, "run", lambda suite: calls.append(suite) or complete())
    assert gate.main(["--strict", "--live", "--output", str(tmp_path)]) == 2
    assert calls == ["deterministic"]
