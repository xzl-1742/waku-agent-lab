"""Bounded dashboard projections of existing traces and checkpoint metadata."""

import json


def group_turns(events):
    turns, active, legacy = [], {}, None
    for event in events:
        kind, key = event.get("type"), event.get("turn_id")
        if kind == "turn_start":
            key = key or f"legacy-{len(turns)}-{event.get('ts')}"
            if not event.get("turn_id"):
                legacy = key
            current = {"user_message": event.get("user_message"), "ts": event.get("ts"),
                       "session_id": event.get("session_id"), "turn_id": key, "gate": None,
                       "llm_calls": [], "model_calls": [], "tools": [], "reply": None}
            active[key] = current
            turns.append(current)
            continue
        current = active.get(key or legacy)
        if current is None:
            continue
        if kind == "gate":
            current["gate"] = event
        elif kind == "route":
            current["graph"] = {"workflow": event.get("workflow"),
                                "route": "quick" if event.get("target") == "quick_reply" else "full",
                                "reason": (current.get("graph") or {}).get("reason", "")}
        elif kind == "triage":
            current.setdefault("graph", {})["reason"] = event.get("reason", "")
        elif kind in ("llm", "model_call", "tool"):
            current[{"llm": "llm_calls", "model_call": "model_calls", "tool": "tools"}[kind]].append(event)
        elif kind == "consolidation":
            current["consolidation"] = event
        elif kind == "turn_end":
            current.update(reply=event.get("reply"), iterations=event.get("iterations"), ended_at=event.get("ts"))
            active.pop(current["turn_id"], None)
    for current in active.values():
        current.update(reply="TURN NEVER FINISHED — check for a hang after this point", unfinished=True)
    return turns


def projection(events, conn, settings):
    wanted = {"context", "compaction_started", "compaction_call", "compaction_completed", "compaction_failed",
              "retrieval", "retrieval_detail", "retrieval_gate_call", "model_call"}
    fields = {"type", "ts", "session_id", "turn_id", "stage", "status", "model", "scope", "estimated_input_tokens",
              "capacity_tokens", "input_budget_tokens", "output_reserve_tokens", "safety_tokens", "estimated_tokens",
              "duration_ms", "duration_seconds", "delivered_ids", "ranked_ids", "new_ids", "omitted", "revision",
              "covered_through", "usage_source", "in", "out", "error_type", "kind", "id", "reason", "capacity_source"}
    recent = [{k: v for k, v in e.items() if k in fields} for e in events if e.get("type") in wanted][-100:][::-1]
    checkpoints = [dict(r) for r in conn.execute(
        "SELECT session_id,revision,covered_through,retained_from,memory_generation FROM session_checkpoints ORDER BY rowid DESC LIMIT 20")]
    generation = conn.execute("SELECT generation FROM memory_state WHERE id=1").fetchone()[0]
    for row in checkpoints:
        row["valid"] = row["memory_generation"] == generation
    comparison = None
    path = settings.home / "comparison_report.json"
    if path.exists():
        try:
            if path.stat().st_size > 2_000_000:
                raise ValueError("Comparison summary is too large")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("summary", {}), dict):
                raise TypeError("Invalid comparison summary")
            comparison = {k: data.get(k) for k in ("experiment", "status", "quality_status", "promotion_status", "trials", "summary", "source")}
        except (OSError, ValueError, TypeError):
            comparison = {"status": "invalid", "quality_status": "incomplete"}
    return {"policies": {k: getattr(settings, k) for k in ("context_policy", "memory_policy", "retrieval_policy")},
            "events": recent, "checkpoints": checkpoints, "comparison": comparison}
