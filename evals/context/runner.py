"""Compare A (window) and B (budget) through Waku sessions, tools and SQLite.

python -m evals.context.runner --split all --output eval-results/context-v0.json
The model is scripted. Passing this run establishes execution coverage only.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evals.context.experiment import policies
from evals.context.fixtures import expand, load_cases
from evals.context.measurement import RecordingClient, digest, metadata, record_tools, request_stage


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 1, 15, 12, tzinfo=UTC)
        return value.astimezone(tz or UTC)

    def astimezone(self, tz=None):
        return super().astimezone(tz or UTC)


class ScenarioClient:
    def __init__(self):
        self.turn = None
        self.pending = []
        self.messages = SimpleNamespace(create=self.create)

    def prepare(self, turn):
        from evals.helpers import response, text_block, tool_block

        if self.pending:
            raise ValueError("Previous turn left unconsumed scripted responses")
        self.turn = turn
        if turn["tools"]:
            self.pending.append(response([
                tool_block(t["name"], t["args"], f"call-{i}")
                for i, t in enumerate(turn["tools"])
            ], stop_reason="tool_use"))
        self.pending.append(response([text_block(turn["reply"])]))

    def create(self, **kwargs):
        from evals.helpers import response, text_block
        stage = request_stage(kwargs)
        if stage == "answer":
            return self.pending.pop(0)
        if stage in ("gate", "selective_gate"):
            query = self.turn["query"]
            text = json.dumps({"retrieve": bool(query), "query": query, "reason": "fixture"})
            if stage == "selective_gate":
                text = json.dumps({**json.loads(text), "mode": "search"})
        elif stage == "consolidation":
            text = '{"facts": [], "episode": ""}'
        elif stage == "lifecycle_consolidation":
            text = '{"facts": [], "episode": null}'
        elif stage == "compaction":
            from evals.context.summary import summarize

            text = summarize(json.loads(kwargs["messages"][0]["content"]))
        else:
            raise ValueError("Unknown model call in scripted baseline")
        return response([text_block(text)])


def build_app(home, client, tool_calls, output_kib, configuration="A", capacity=32768):
    from evals.helpers import make_waku
    from waku.tools.registry import Tool

    app = make_waku(home, client=client, provider="anthropic", model="scripted-answer",
                    small_model="scripted-small", history_turns=12, consolidate_every=6,
                    retrieval_top_k=4, max_iterations=10, max_tokens=8192,
                    semantic_store="sqlite", episodic_store="sqlite",
                    **policies(configuration),
                    context_window_tokens=capacity, small_context_window_tokens=capacity,
                    experimental=False, gh_tool=False)
    app.conn.execute("CREATE TABLE IF NOT EXISTS eval_actions (receipt TEXT NOT NULL)")

    def record_action(receipt):
        app.conn.execute("INSERT INTO eval_actions VALUES (?)", (receipt,))
        app.conn.commit()
        return receipt

    app.tools.register(Tool("record_action", "Record a synthetic local action.",
                            {"type": "object", "properties": {"receipt": {"type": "string"}},
                             "required": ["receipt"]}, record_action))
    app.tools.register(Tool("read_fixture", "Read an irrelevant synthetic log.",
                            {"type": "object", "properties": {}},
                            lambda: "x" * (output_kib * 1024)))
    record_tools(app.tools, tool_calls)
    return app


def run_case(case, home, configuration="A", capacity=32768):
    # This runner must never create a persistent home alongside a user's files.
    if not os.environ.get("WAKU_EVAL_ROOT") or not home.resolve().is_relative_to(
        Path(os.environ["WAKU_EVAL_ROOT"]).resolve()
    ):
        raise RuntimeError("Run context baselines through the offline isolation bootstrap")
    if configuration not in ("A", "B", "B2", "V3-window", "V3-compact", "V5-A", "V5-B", "V5-C", "V5-D"):
        raise ValueError("Unknown implemented configuration")
    script = ScenarioClient()
    client = RecordingClient(script, synthetic=True)
    tool_calls, turn_seconds, checks = [], [], []
    app = build_app(home, client, tool_calls, case["output_kib"], configuration, capacity)
    app.session.start_new("primary-project")
    steps = expand(case)
    started = time.perf_counter()
    final_input, errors, context_events = "", [], []
    replies = []

    def observe(kind, event):
        if kind in ("context", "context_error", "gate", "retrieval", "retrieval_detail") or kind.startswith("compaction_"):
            context_events.append({"kind": kind, **event})
    try:
        with patch("datetime.datetime", FixedDatetime):
            for step in steps:
                if step["op"] == "switch":
                    app.session.switch(step["session"])
                elif step["op"] == "restart":
                    app.close()
                    app.conn.close()
                    app = build_app(home, client, tool_calls, case["output_kib"], configuration, capacity)
                    app.session.switch(step["session"])
                elif step["op"] == "turn":
                    script.prepare(step)
                    turn_start = time.perf_counter()
                    generation = app.memory.lifecycle.generation
                    result = app.respond(step["message"], stream=False, source="eval", observer=observe)
                    replies.append({"message": step["message"], "reply": result.reply,
                                    "tools": result.tool_calls, "session_id": app.session.session_id})
                    if app.memory.lifecycle.generation > generation:
                        # Lifecycle mutations intentionally finish without the
                        # scripted model's final reply. Require the real receipt.
                        if "memory" not in result.reply.lower() or len(script.pending) != 1:
                            raise ValueError("Missing deterministic mutation acknowledgement")
                        script.pending.pop()
                    turn_seconds.append(time.perf_counter() - turn_start)
                    if script.pending:
                        raise ValueError("Model response script was not fully consumed")
                else:
                    raise ValueError(f"Unknown scenario operation: {step['op']}")
        final_input = client.last_main_input
        facts = [r["content"] for r in app.conn.execute("SELECT content FROM facts WHERE validity='active' ORDER BY id")]
        actions = [r["receipt"] for r in app.conn.execute("SELECT receipt FROM eval_actions")]
        chats = app.conn.execute("SELECT COUNT(*) FROM chat_log").fetchone()[0]
        expected_facts = ([case["current"]] if case["family"] in ("corrections", "retrieval") else [])
        expected_actions = [case["old"]] if case["family"] == "tools" else []
        checks = [
            {"name": "stored_facts", "passed": facts == expected_facts,
             "expected": expected_facts, "actual": facts},
            {"name": "side_effects", "passed": actions == expected_actions,
             "expected": expected_actions, "actual": actions},
            {"name": "persistent_turns", "passed": chats == case["turns"] * 2,
             "expected": case["turns"] * 2, "actual": chats},
            {"name": "calls_completed", "passed": all(c["status"] == "complete"
                                                         for c in client.calls + tool_calls)},
            {"name": "session_transcript_isolation",
             "passed": "OTHER_SESSION_SENTINEL" not in final_input},
        ]
        if policies(configuration)["memory_policy"] == "lifecycle" and case["family"] in ("corrections", "forgetting"):
            checks.append({"name": "suppressed_fact_absent", "passed": case["old"] not in final_input})
        if policies(configuration)["memory_policy"] == "lifecycle" and case["family"] == "corrections":
            checks.append({"name": "corrected_fact_available", "passed": case["current"] in final_input})
        if policies(configuration)["context_policy"] != "window":
            executions = app.conn.execute("SELECT * FROM tool_executions").fetchall()
            checks.extend([
                {"name": "request_budgets", "passed": all(
                    c["estimated_input_tokens"] + c["max_tokens"] + 1024 <= capacity
                    for c in client.calls)},
                {"name": "artifacts_recoverable", "passed": all(
                    e["state"] == "complete" and app.records.path(e["result_id"]).stat().st_size == e["result_bytes"]
                    for e in executions) and len(executions) == len(tool_calls)},
                {"name": "canonical_messages_saved", "passed": app.conn.execute(
                    "SELECT COUNT(*) FROM session_messages").fetchone()[0] >= chats},
            ])
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        app.close()
        app.conn.close()
    elapsed = time.perf_counter() - started
    from waku.ops.usage import read_ledger, summarize

    return {
        "id": case["id"], "family": case["family"], "split": case["split"],
        "configuration": configuration,
        "status": "complete" if checks and all(c["passed"] for c in checks) and not errors else "failed",
        "trial": 1, "expanded_fixture_sha256": digest(steps), "errors": errors,
        "outcome_checks": checks, "quality_status": "incomplete", "task_success": None,
        "input_tokens": None, "output_tokens": None, "cost_usd": None,
        "usage_source": "synthetic", "model_calls": len(client.calls),
        "calls_by_stage": dict(Counter(c["stage"] for c in client.calls)),
        "stage_seconds": {stage: sum(c["duration_seconds"] for c in client.calls if c["stage"] == stage)
                          for stage in ("gate", "answer", "consolidation", "lifecycle_consolidation", "compaction")},
        "tool_seconds": sum(c["duration_seconds"] for c in tool_calls),
        "duration_seconds": elapsed, "turn_seconds": turn_seconds,
        "calls": client.calls, "tool_calls": tool_calls,
        "context_events": context_events,
        "replies": replies, "usage": summarize(read_ledger(home)),
        "estimated_input_tokens_total": sum(c["estimated_input_tokens"] for c in client.calls),
        "estimated_input_tokens_peak": max((c["estimated_input_tokens"] for c in client.calls), default=0),
        "evidence_probes": {
            "current_fact_in_final_input": case["current"] in final_input,
            "obsolete_fact_in_final_input": (case["old"] in final_input
                                            if case["old"] != case["current"] else None),
        },
    }


def make_report(cases, root, configuration="A", capacity=32768):
    results = [run_case(case, root / case["id"], configuration, capacity) for case in cases]
    durations = sorted(t for case in results for t in case["turn_seconds"])
    return {
        **metadata(configuration, capacity), "status": "failed" if any(c["status"] == "failed" for c in results) else "complete",
        "quality_status": "incomplete", "live": {"status": "skipped", "reason": "not requested"},
        "unavailable_configurations": ["C", "D"],
        "measurement_limits": ["Scripted replies cannot establish model quality or token cost.",
                               "Call counts measure client invocations, excluding hidden SDK retries.",
                               "Consolidation outputs empty facts; extraction quality is unmeasured.",
                               "Evidence probes inspect input availability, not model understanding.",
                               "Estimated input counts use UTF-8 JSON bytes, not provider token usage.",
                               "B includes result-read instructions and schemas; A retains the old prompt.",
                               "Shared correctness fixes and additive DB schema apply to both A and B."],
        "summary": {"scenarios": len(results), "complete": sum(c["status"] == "complete" for c in results),
                    "turns": len(durations), "model_calls": sum(c["model_calls"] for c in results),
                    "estimated_input_tokens_total": sum(c["estimated_input_tokens_total"] for c in results),
                    "estimated_input_tokens_peak": max((c["estimated_input_tokens_peak"] for c in results), default=0),
                    "budget_violations": sum(c["estimated_input_tokens"] + c["max_tokens"] + 1024 > capacity
                                             for case in results for c in case["calls"]),
                    "rejected_requests": sum(e.get("stage") == "rejected" for case in results for e in case["context_events"]),
                    "turn_median_seconds": statistics.median(durations) if durations else None,
                    "turn_p95_seconds": durations[max(0, (95 * len(durations) + 99) // 100 - 1)] if durations else None,
                    "input_tokens": None, "output_tokens": None, "cost_usd": None},
        "cases": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["development", "reserved", "all"], default="development")
    parser.add_argument("--configuration", choices=["A", "B", "B2", "V3-window", "V3-compact"], default="A")
    parser.add_argument("--capacity", type=int, default=32768)
    parser.add_argument("--output", type=Path, default=Path("eval-results/context-v0.json"))
    args = parser.parse_args(argv)
    from evals.isolation import install

    scratch = install()
    cases = [c for c in load_cases() if args.split == "all" or c["split"] == args.split]
    with tempfile.TemporaryDirectory(prefix="context-", dir=scratch) as root:
        report = make_report(cases, Path(root), args.configuration, args.capacity)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "quality_status": report["quality_status"],
                      **report["summary"]}, indent=2))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
