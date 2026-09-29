"""Regrade an immutable exploratory report without replaying any user task."""

import copy
import hashlib
import json

from evals.context.measurement import digest, source_snapshot
from evals.context.probes import grade_probes, metrics, probe_status
from evals.context.quality import aggregate, calibrate, grade


def regrade(original, client, model, should_stop=lambda: False):
    if original.get("schema_version") != 3 or original.get("runner") != "live-exploratory":
        raise ValueError("Regrading requires captured version-3 exploratory evidence")
    result = copy.deepcopy(original)
    result.update(runner="live-rejudge", quality_status="incomplete", promotion_status="incomplete")
    result.pop("pilot", None)
    allowed_errors = {None, "JSONDecodeError", "ValueError", "ProbeCoverageIncomplete"}
    for row in result["cases"]:
        row["previous_judgment"] = {k: copy.deepcopy(row.get(k)) for k in ("verdict", "error_type", "task_success", "probe_metrics")}
        if should_stop():
            row.update(status="failed", error_type="PilotStopped", task_success=None)
            continue
        if (row.get("runtime_error_type") or len(row.get("replies", [])) != row["turns"]
                or row.get("error_type") not in allowed_errors or row["probes"].get("capture_errors")):
            continue  # A judge cannot repair missing runtime or capture evidence.
        if not row.get("judge_input"):
            raise ValueError("Saved judge evidence is missing")
        row["probes"]["checks"] = []
        row.update(verdict=None, error_type=None, task_success=None)
        try:
            row["verdict"] = grade(client, model, row["judge_input"])
            grade_probes(row["probes"], client, model)
            if probe_status(row["probes"]) == "incomplete":
                raise ValueError("Incomplete regraded probe coverage")
            v = row["verdict"]
            row["task_success"] = v["task_success"] and not v["stale_assertion"] and not v["unsupported_assertion"] and row["action_check"] and probe_status(row["probes"]) == "complete"
        except Exception as exc:
            row["error_type"] = type(exc).__name__
        row["status"] = "failed" if row["error_type"] else "complete"
        row["probe_metrics"] = metrics(row["probes"])
        print(f'Regraded {row["id"]}/{row["arm"]}: {row["status"]}', flush=True)
    result["status"] = "complete" if len(result["cases"]) == result["expected_runs"] and all(r["status"] == "complete" for r in result["cases"]) else "incomplete"
    result.update(aggregate(result["cases"], [(r["id"], r["configuration"], r["trial"]) for r in result["cases"]]))
    return result


def execute(path, output, settings, make_client, should_stop):
    import dotenv
    import dotenv.main
    dotenv.load_dotenv = dotenv.main.load_dotenv = lambda *a, **k: False
    dotenv.find_dotenv = dotenv.main.find_dotenv = lambda *a, **k: ""
    from waku.ops.accounting import UsageClient
    from waku.ops.usage import summarize

    data = path.read_bytes()
    original = json.loads(data)
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    def record(row):
        rows.append(row)
        with (output / "model-calls.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    source = source_snapshot()
    client = UsageClient(make_client(settings), settings, record)
    labels = json.loads(settings.calibration.read_text(encoding="utf-8"))
    calibration = calibrate(client, settings.judge_model, labels["cases"], provisional=True,
                            required_kinds={"answer", "checkpoint", "memory_support", "memory_recall"})
    calibration.update(labels_sha256=digest(labels), reviewer="")
    result = regrade(original, client, settings.judge_model, should_stop)
    result["calibration"] = calibration
    result["regrade"] = {"original_report_sha256": hashlib.sha256(data).hexdigest(),
                         "source": source, "source_end": source_snapshot(), "usage": summarize(rows, {})}
    (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
