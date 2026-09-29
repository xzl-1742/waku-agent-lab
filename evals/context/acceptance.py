"""Recompute release evidence from validated rows, never trust display totals."""

import json
import math

from evals.context.experiment import manifest
from evals.context.fixtures import load_cases
from evals.context.measurement import digest
from evals.context.probes import probe_status

PROBE_KINDS = {"answer", "checkpoint", "memory_support", "memory_recall"}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def calibrated(record):
    from evals.context.quality import RUBRIC, validate

    try:
        if (record.get("status") != "complete" or not record.get("reviewer") or not record.get("labels_sha256")
                or not record.get("model") or record.get("rubric") != RUBRIC):
            return False
        rows = record["results"]
        if not rows or len({r["id"] for r in rows}) != len(rows) or not PROBE_KINDS <= {r["kind"] for r in rows}:
            return False
        if any({r["expected"]["task_success"] for r in rows if r["kind"] == kind} != {True, False} for kind in PROBE_KINDS):
            return False
        passed = []
        labels = {"task_success", "stale_assertion", "unsupported_assertion"}
        for row in rows:
            if set(row["expected"]) != labels or any(type(v) is not bool for v in row["expected"].values()):
                return False
            verdict = validate(json.dumps(row["verdict"]))
            correct = all(verdict[k] == v for k, v in row["expected"].items())
            passed.append(correct)
            if not correct and (row["expected"]["stale_assertion"] or row["expected"]["unsupported_assertion"]):
                return False
        coverage = all(any(r["expected"][key] for r in rows) for key in labels)
        return coverage and sum(passed) / len(passed) >= manifest()["promotion"]["minimum_judge_calibration_agreement"]
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def validate_rows(report, *, all_cases=True):
    """Return normalized rows, or None for missing, malformed or partial evidence."""
    from evals.context.quality import validate

    try:
        bank = {c["id"]: c for c in load_cases()}
        trials = report.get("trials")
        if type(trials) is not int or (trials != 5 and all_cases) or not 1 <= trials <= 5:
            return None
        rows = report["cases"]
        if not isinstance(rows, list):
            return None
        expected = {(key, f"V5-{a}", t) for key, c in bank.items() if all_cases or c["split"] == "reserved"
                    for a in "ABCD" for t in range(1, trials + 1)}
        seen, normalized = set(), []
        for row in rows:
            identity = (row["id"], row["configuration"], row["trial"])
            if identity in seen or row["id"] not in bank or row["configuration"] not in {f"V5-{a}" for a in "ABCD"}:
                return None
            if type(row["trial"]) is not int or not 1 <= row["trial"] <= trials:
                return None
            seen.add(identity)
            case = bank[row["id"]]
            if row.get("family") != case["family"] or row.get("turns") != case["turns"]:
                return None
            verdict = validate(json.dumps(row["verdict"]))
            probes = probe_status(row.get("probes"), case)
            if row.get("status") != "complete" or row.get("error_type") or probes == "incomplete":
                return None
            durations = row["turn_seconds"]
            if len(durations) != case["turns"] or any(not finite(t) for t in durations):
                return None
            usage = row["usage"]["runtime"]
            if type(usage.get("usage_complete")) is not bool or not finite(usage.get("calls")):
                return None
            if usage["usage_complete"] and any(type(usage.get(k)) is not int or usage[k] < 0 for k in ("input_tokens", "output_tokens")):
                return None
            if not isinstance(row.get("actual_actions"), list):
                return None
            action_ok = row["actual_actions"] == ([case["old"]] if case["family"] == "tools" else [])
            task_ok = verdict["task_success"] and not verdict["stale_assertion"] and not verdict["unsupported_assertion"] and action_ok and probes == "complete"
            # Derived values are recomputed even if an imported report claims otherwise.
            normalized.append({**row, "split": case["split"], "action_check": action_ok, "task_success": task_ok})
        if not expected <= seen or all_cases and seen != expected:
            return None
        return normalized
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def source_stable(report):
    start, end = report.get("source"), report.get("source_end")
    return bool(isinstance(start, dict) and start.get("manifest_sha256") and start == end and report.get("source_stable") is True)


def header_complete(report):
    return (report.get("schema_version") == 3 and report.get("runner") == "live" and report.get("status") == "complete"
            and report.get("quality_status") == "complete" and source_stable(report)
            and report.get("manifest_sha256") == digest(manifest()) and calibrated(report.get("calibration", {})))


def secondary(report, primary):
    valid = isinstance(report, dict) and header_complete(report) and report.get("provider") and report["provider"] != primary
    rows = validate_rows(report, all_cases=False) if valid else None
    passed = rows is not None and all(r["task_success"] for r in rows if r["configuration"] in ("V5-C", "V5-D"))
    return {"status": "complete" if passed else "incomplete", "provider": report.get("provider") if isinstance(report, dict) else None,
            "report_sha256": digest(report) if report is not None else None}


def decide(metrics):
    """The quality route does not require the alternative efficiency benefit."""
    needed = ("long_task_gain_lower_95", "short_task_change_lower_95", "short_latency_ratio_upper_95", "critical_failures")
    if any(type(metrics.get(k)) not in (int, float) or not math.isfinite(metrics[k]) for k in needed):
        return "incomplete"
    gates = manifest()["promotion"]
    if (metrics["critical_failures"] or metrics["short_task_change_lower_95"] < -gates["maximum_short_task_regression"]
            or metrics["short_latency_ratio_upper_95"] > 1 + gates["maximum_short_latency_increase"]):
        return "failed"
    if metrics["long_task_gain_lower_95"] >= gates["long_task_gain"]:
        return "complete"
    baseline, reduction = metrics.get("baseline_long_success"), metrics.get("runtime_reduction_lower_95")
    if not finite(baseline) or baseline < gates["baseline_quality_ceiling"]:
        return "inconclusive"
    if type(reduction) not in (int, float) or not math.isfinite(reduction):
        return "incomplete"
    return "complete" if reduction >= gates["alternative_runtime_reduction"] else "inconclusive"


def promote(report):
    from evals.context.quality import aggregate

    if not isinstance(report, dict):
        return "incomplete"
    if report.get("status") == "failed":
        return "failed"
    if any(report.get("summary", {}).get("arms", {}).get(a, {}).get("critical_failures") for a in ("C", "D")):
        return "failed"
    rows = validate_rows(report)
    if rows is None:
        return "incomplete"
    if any(not r["task_success"] and (r["family"] in manifest()["critical_families"] or probe_status(r["probes"]) == "failed")
           for r in rows if r["configuration"] in ("V5-C", "V5-D")):
        return "failed"
    if not header_complete(report) or secondary(report.get("second_provider_evidence"), report.get("provider"))["status"] != "complete":
        return "incomplete"
    # Reserved cases receive their own acceptance decision; development gains
    # cannot offset a reserved regression. Persisted aggregate fields are UI data.
    decisions = []
    for subset in (rows, [r for r in rows if r["split"] == "reserved"]):
        expected = [(r["id"], r["configuration"], r["trial"]) for r in subset]
        decisions.append(decide(aggregate(subset, expected)["quality_metrics"]))
    return next((state for state in ("failed", "incomplete", "inconclusive") if state in decisions), "complete")
