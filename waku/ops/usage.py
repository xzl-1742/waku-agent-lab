"""Strict usage totals; incomplete measurements never turn into zero cost."""

import json
from collections import Counter


def read_ledger(home):
    path = home / "usage.jsonl"
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except json.JSONDecodeError:
                rows.append({"status": "invalid", "in": None, "out": None})
    return rows


def strict_cost(row, rates=None):
    """Rates must be explicitly supplied with provenance, never a provider guess."""
    rate = (rates or {}).get((row.get("provider"), row.get("model")))
    if not rate or not rate.get("source") or row.get("in") is None or row.get("out") is None:
        return None
    cached = row.get("cache_read_input_tokens") or 0
    created = row.get("cache_creation_input_tokens") or 0
    if (cached and "cached_input" not in rate) or (created and "cache_creation" not in rate):
        return None
    normal = row["in"] - cached if row.get("cache_included_in_input") else row["in"]
    if normal < 0:
        return None
    return (normal * rate["input"] + row["out"] * rate["output"]
            + cached * rate.get("cached_input", 0) + created * rate.get("cache_creation", 0)) / 1e6


def summarize(rows, rates=None):
    def group(items):
        known = [r for r in items if r.get("in") is not None and r.get("out") is not None]
        costs = [strict_cost(r, rates) for r in items]
        complete = len(known) == len(items)
        total = sum(r["in"] + (0 if r.get("cache_included_in_input") else
                    (r.get("cache_read_input_tokens") or 0) + (r.get("cache_creation_input_tokens") or 0)) for r in known)
        outgoing = sum(r["out"] for r in known)
        return {"calls": len(items), "failed_calls": sum(r.get("status") == "failed" for r in items),
                "unmeasured_calls": len(items) - len(known), "usage_complete": complete,
                "input_tokens": total if complete else None, "output_tokens": outgoing if complete else None,
                "known_input_tokens": total, "known_output_tokens": outgoing,
                "cost_usd": sum(costs) if all(c is not None for c in costs) else None,
                "known_cost_usd": sum(c for c in costs if c is not None),
                "unpriced_calls": sum(c is None for c in costs),
                "by_stage": dict(Counter(r.get("stage", r.get("kind", "legacy")) for r in items))}
    return {"runtime": group([r for r in rows if r.get("scope") != "judge"]),
            "judge": group([r for r in rows if r.get("scope") == "judge"]),
            "boundary": "SDK invocations; hidden SDK retries excluded"}
