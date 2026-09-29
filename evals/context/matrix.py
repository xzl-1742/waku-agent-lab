"""Run the frozen V5 A/B/C/D matrix offline; quality remains unmeasured.

python -m evals.context.matrix --split all --trials 5 --output eval-results/context-v5.json
"""

import argparse
import json
import random
import tempfile
from pathlib import Path

from evals.context.comparison import summarize
from evals.context.experiment import manifest
from evals.context.fixtures import load_cases
from evals.context.measurement import digest, source_snapshot


def run(cases, root, trials=5, progress=None):
    from evals.context.runner import run_case

    config = manifest()
    source = source_snapshot()
    expected = [(c["id"], f"V5-{arm}", trial) for c in cases for trial in range(1, trials + 1) for arm in config["arms"]]
    order = list(expected)
    random.Random(config["seed"]).shuffle(order)
    bank = {c["id"]: c for c in cases}
    results = []
    for i, (case_id, arm, trial) in enumerate(order):
        row = run_case(bank[case_id], root / arm / f"trial-{trial}" / case_id, arm, config["capacity"])
        row["trial"] = trial
        results.append(row)
        if progress:
            progress(i + 1, len(order), row)
    summary = summarize(results, expected, config)
    status = "complete" if summary["coverage_complete"] and all(r["status"] == "complete" for r in results) else "failed"
    final_source = source_snapshot()
    return {"schema_version": 1, "experiment": config["experiment"], "manifest": config,
            "manifest_sha256": digest(config), "source": source, "source_end": final_source,
            "source_stable": source == final_source, "order": order,
            "trials": trials, "status": status, "quality_status": "incomplete", "promotion_status": "incomplete",
            "summary": summary, "cases": results, "judge_cost_usd": None,
            "limits": ["Scripted replies and extraction do not measure task or judge quality.",
                       "Intervals describe paired fixture variation, not independent repeated model samples.",
                       "Local timings are diagnostic; provider tokens and complete cost remain unmeasured.",
                       "V5 labels are versioned; historical B means budget, V5-B means compact."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("development", "reserved", "all"), default="development")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("eval-results/context-v5.json"))
    args = parser.parse_args()
    if not 1 <= args.trials <= 5:
        parser.error("trials must be between 1 and 5")
    from evals.isolation import install

    scratch = install()
    cases = [c for c in load_cases() if args.split == "all" or c["split"] == args.split]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    partial = args.output.with_suffix(".partial.jsonl")
    if partial.exists():
        parser.error("Partial report already exists; choose a new output path to preserve prior results")
    with partial.open("w", encoding="utf-8") as handle:
        def progress(done, total, row):
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            print(f'{done}/{total} {row["configuration"]} {row["id"]} trial={row["trial"]} {row["status"]}', flush=True)
        with tempfile.TemporaryDirectory(prefix="matrix-", dir=scratch) as root:
            report = run(cases, Path(root), args.trials, progress)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "summary": report["summary"]}, indent=2))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
