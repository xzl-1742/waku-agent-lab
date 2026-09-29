"""Offline checks and an explicit, fail-closed quality gate.

python -m waku.ops.release_gate --strict --live --output eval-results
Live evaluation is opt-in and can spend API credits. Imports never load keys.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def skipped(reason: str) -> dict:
    return {"status": "skipped", "reason": reason, "passed": 0, "failed": 0,
            "errors": 0, "skipped": 0, "duration_seconds": None}


def read_result(path: Path, exit_code: int, elapsed: float) -> dict:
    """JUnit distinguishes collection errors and all-skipped runs from passes."""
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    if path.exists():
        try:
            for case in ET.parse(path).iter("testcase"):
                outcome = next((k for tag, k in (("failure", "failed"), ("error", "errors"),
                                               ("skipped", "skipped"))
                                if case.find(tag) is not None), "passed")
                counts[outcome] += 1
        except ET.ParseError:
            return {**skipped("invalid pytest result"), "status": "failed",
                    "duration_seconds": elapsed}
    if exit_code not in (0, 5) or counts["failed"] or counts["errors"]:
        status, reason = "failed", f"pytest exited {exit_code}"
    elif not counts["passed"]:
        status, reason = "skipped", "no checks passed (missing, empty or entirely skipped suite)"
    else:
        status, reason = "complete", ""
    return {**counts, "status": status, "reason": reason, "duration_seconds": elapsed}


def run(suite: str) -> dict:
    if suite not in ("deterministic", "judge"):
        raise ValueError(f"Unknown eval suite: {suite}")
    print(f"\n=== {suite} ===")
    with tempfile.TemporaryDirectory(prefix="waku-gate-") as scratch:
        junit = Path(scratch) / "result.xml"
        module = "evals.offline" if suite == "deterministic" else "pytest"
        env = dict(os.environ)
        if suite == "judge":
            env["WAKU_RUN_LIVE_EVALS"] = "1"
        env["PYTHONUTF8"] = "1"
        started = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, "-m", module, "-q", str(REPO / "evals" / suite),
             f"--junitxml={junit}"], cwd=REPO, env=env,
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        elapsed = time.perf_counter() - started
        print(proc.stdout, end="")
        print(proc.stderr, end="", file=sys.stderr)
        return read_result(junit, proc.returncode, elapsed)


def verdict(suites: dict) -> str:
    required = ("deterministic", "judge")
    if any(suites.get(name, {}).get("status") == "failed" for name in required):
        return "failed"
    if any(suites.get(name, {}).get("status") != "complete" for name in required):
        return "incomplete"
    if suites["judge"].get("skipped", 0):
        return "incomplete"
    return "complete"


def report(suites: dict, output: Path, comparison=None) -> dict:
    """Keep legacy dashboard fields while recording explicit suite coverage."""
    legacy = {"complete": "pass", "failed": "fail", "skipped": "skipped"}
    record = {
        "schema_version": 1, "status": verdict(suites),
        **{name: legacy.get(suites.get(name, {}).get("status"), "not run")
           for name in ("deterministic", "judge")},
        "suites": suites, "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if comparison is not None:
        record["comparison"] = comparison
        if comparison["status"] == "failed":
            record["status"] = "failed"
        elif comparison["status"] != "complete" and record["status"] != "failed":
            record["status"] = "incomplete"
    output.mkdir(parents=True, exist_ok=True)
    (output / "eval_report.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    with (output / "eval_runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="Reject incomplete live coverage")
    parser.add_argument("--live", action="store_true", help="Allow credential loading and paid judges")
    parser.add_argument("--output", type=Path, default=Path("eval-results"))
    parser.add_argument("--comparison", type=Path, help="Require a V5 combined-system comparison artifact")
    args = parser.parse_args(argv)
    suites = {"deterministic": run("deterministic")}
    suites["judge"] = skipped("live evaluation was not requested")
    if suites["deterministic"]["status"] == "complete" and args.live:
        from waku.config import load_settings
        from waku.loop.models import PROVIDERS

        settings = load_settings()
        provider = PROVIDERS.get(settings.provider)
        has_key = bool(settings.api_key or (provider and os.getenv(provider.key_env)))
        suites["judge"] = (run("judge") if has_key
                           else skipped(f"no credentials for {settings.provider}"))
    comparison_result = None
    if args.comparison:
        from evals.context.quality import promotion

        try:
            comparison = json.loads(args.comparison.read_text(encoding="utf-8"))
            result = promotion(comparison)
        except (OSError, ValueError, TypeError):
            result = "incomplete"
        comparison_result = {"status": result, "path": str(args.comparison)}
    record = report(suites, args.output, comparison_result)
    if record["status"] == "failed":
        print("GATE CLOSED: evaluation failed.")
        return 1
    if record["status"] == "incomplete":
        print("QUALITY INCOMPLETE: live coverage is missing or skipped.")
        return 2 if args.strict or suites["deterministic"]["status"] != "complete" else 0
    print("GATE OPEN: required suites completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
