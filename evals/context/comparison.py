"""Compare paired scenarios without treating repeated scripts as model trials."""

import random
import statistics
from collections import defaultdict


def paired_interval(results, candidate, control, metric, seed=20260929, samples=1000):
    pairs = defaultdict(dict)
    for row in results:
        if row["configuration"] in (candidate, control):
            pairs[(row["id"], row["trial"])][row["configuration"]] = row
    clusters, families, missing = defaultdict(list), {}, 0
    for (case_id, _), pair in pairs.items():
        if set(pair) != {candidate, control} or any(pair[a].get(metric) is None for a in (candidate, control)):
            missing += 1
            continue
        clusters[case_id].append(pair[candidate][metric] - pair[control][metric])
        families[case_id] = pair[candidate]["family"]
    means = {key: statistics.mean(values) for key, values in clusters.items()}
    if not means:
        return {"delta": None, "interval_95": None, "paired_scenarios": 0, "missing_pairs": missing}
    groups = defaultdict(list)
    for key, value in means.items():
        groups[families[key]].append(value)
    rng = random.Random(seed)
    bootstrap = sorted(statistics.mean(v for values in groups.values() for v in rng.choices(values, k=len(values)))
                       for _ in range(samples))
    return {"delta": statistics.mean(means.values()), "interval_95": [bootstrap[int(samples * .025)], bootstrap[int(samples * .975)]],
            "paired_scenarios": len(means), "missing_pairs": missing,
            "method": "paired scenario clusters, stratified by family; repetitions stay together"}


def summarize(results, expected, config):
    arms = {}
    for arm in config["arms"]:
        rows = [r for r in results if r["configuration"] == f"V5-{arm}"]
        durations = sorted(t for r in rows for t in r["turn_seconds"])
        arms[arm] = {"runs": len(rows), "complete": sum(r["status"] == "complete" for r in rows),
                     "turns": len(durations), "model_calls": sum(r["model_calls"] for r in rows),
                     "estimated_input_tokens": sum(r["estimated_input_tokens_total"] for r in rows),
                     "turn_median_seconds": statistics.median(durations) if durations else None,
                     "turn_p95_seconds": durations[min(len(durations) - 1, int(len(durations) * .95))] if durations else None,
                     "input_tokens": None, "cost_usd": None,
                     "critical_failures": [f'{r["id"]}/{r["trial"]}' for r in rows
                                           if r["family"] in config["critical_families"] and r["status"] != "complete"]}
    seen = {(r["id"], r["configuration"], r["trial"]) for r in results}
    complete = len(seen) == len(results) and seen == set(expected)
    return {"coverage_complete": complete, "expected_runs": len(expected), "actual_runs": len(results),
            "arms": arms, "pairs": {
                f"{a}-{b}": {metric: paired_interval(results, f"V5-{a}", f"V5-{b}", metric)
                             for metric in ("estimated_input_tokens_total", "duration_seconds", "task_success")}
                for a, b in [config["primary_pair"], *config["secondary_pairs"]]}}
