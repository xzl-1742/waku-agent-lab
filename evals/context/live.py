"""Explicit live V5 execution against disposable stores and local-only tools.

The default prints a credential-free plan. Execution requires --live, explicit
model IDs, a reviewed calibration file and a model-call allowance. It never
loads dotenv files. Runtime and judge ledgers remain separate in the report.
"""

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from evals.context.experiment import manifest
from evals.context.fixtures import expand, load_cases


def plan(split="reserved", trials=5):
    cases = [c for c in load_cases() if split == "all" or c["split"] == split]
    return {"experiment": manifest()["experiment"], "mode": "plan", "credentials_loaded": False,
            "scenarios": len(cases), "arms": manifest()["arms"], "trials": trials,
            "scenario_runs": len(cases) * 4 * trials,
            "user_turns": sum(c["turns"] for c in cases) * 4 * trials,
            "cost_usd": None, "reason": "Real usage and explicit rate provenance are required",
            "tools": ["save_note", "manage_memory", "record_action", "read_fixture"]}


def execute(args, *, client_factory=None, should_stop=None):
    # Only an explicit command may reach this point. Discovery of a user's
    # dotenv is disabled before configuration or provider modules are imported.
    if not args.live:
        raise ValueError("Live execution must be explicit")
    import dotenv
    import dotenv.main
    dotenv.load_dotenv = dotenv.main.load_dotenv = lambda *a, **k: False
    dotenv.find_dotenv = dotenv.main.find_dotenv = lambda *a, **k: ""
    from evals.context.measurement import digest, source_snapshot
    from evals.context.probes import ProbeCapture, grade_probes, metrics, probe_status
    from evals.context.quality import blind, calibrate, grade
    from waku.app import Waku
    from waku.config import Settings
    from waku.loop.models import PROVIDERS, get_client
    from waku.ops.accounting import UsageClient
    from waku.ops.tracing import Tracer
    from waku.ops.usage import summarize
    from waku.tools.registry import Tool

    make_client = client_factory or get_client
    exploratory = getattr(args, "exploratory", False)
    cases = [c for c in load_cases() if args.split == "all" or c["split"] == args.split]
    selected = set(getattr(args, "case_ids", None) or [])
    if selected:
        if not selected <= {c["id"] for c in cases}:
            raise ValueError("Unknown case IDs for the selected split")
        cases = [c for c in cases if c["id"] in selected]
    provider = PROVIDERS.get(args.provider)
    if provider is None:
        raise ValueError("Unknown provider")
    credential = os.environ.get(provider.key_env)
    if not credential:
        raise ValueError(f"Set {provider.key_env} in the process environment; dotenv loading is disabled")
    labels = json.loads(args.calibration.read_text(encoding="utf-8"))
    if not exploratory and (labels.get("reviewed") is not True or not labels.get("reviewer") or not labels.get("cases")):
        raise ValueError("Calibration needs an independent reviewer and labelled examples")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    all_rows, results = [], []
    config = manifest()
    source = source_snapshot()
    from waku.ops.usage import load_rates
    rates = load_rates(args.rates) if getattr(args, "rates", None) else {}
    calls = [0]

    def save(report):
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def record_usage(row, destination):
        destination.append(row)
        with (output / "model-calls.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    class LimitedClient:
        def __init__(self, client):
            from types import SimpleNamespace
            self.client = client
            self.messages = SimpleNamespace(create=self.create)

        def __getattr__(self, name):
            return getattr(self.client, name)

        @property
        def notify(self):
            return getattr(self.client, "notify", None)

        @notify.setter
        def notify(self, value):
            self.client.notify = value

        def create(self, **request):
            if calls[0] >= args.max_calls or (should_stop is not None and should_stop()):
                from waku.runtime.context import TurnStopped
                raise TurnStopped("Live evaluation call allowance exhausted")
            calls[0] += 1
            return self.client.messages.create(**request)

    def settings(home, arm):
        return Settings(home=home, provider=args.provider, api_key=credential, model=args.model,
            small_model=args.small_model, **config["arms"][arm], context_window_tokens=config["capacity"],
            small_context_window_tokens=config["capacity"], compaction_model=args.model,
            compaction_context_tokens=config["capacity"], history_turns=12, consolidate_every=6,
            context_safety_tokens=1024, tool_output_bytes=4096, compaction_max_tokens=2048,
            compaction_keep_turns=4, compaction_max_calls=32, consolidation_input_tokens=16000,
            memory_scope="global", project_id="",
            semantic_store="sqlite", episodic_store="sqlite", retrieval_top_k=4,
            retrieval_tokens=1024, retrieval_gate_tokens=2048, max_tokens=8192, max_iterations=10,
            experimental=False, gh_tool=False, graph_workflows=False, apple_tools=False,
            apple_calendar=False, google_calendar=False, base_url=None, otel_endpoint="")

    with tempfile.TemporaryDirectory(prefix="v5-live-") as scratch:
        root = Path(scratch)
        judge_settings = settings(root / "judge", "A")
        judge_settings.model = args.judge_model
        judge_settings.ensure_home()
        judge_rows = []
        try:
            judge = LimitedClient(UsageClient(make_client(judge_settings), judge_settings,
                                             lambda row: record_usage(row, judge_rows)))
        except Exception as exc:
            return save({"status": "incomplete", "quality_status": "incomplete", "error_type": type(exc).__name__,
                         "reason": "Judge client initialization failed", "promotion_status": "incomplete"})
        calibration = calibrate(judge, args.judge_model, labels["cases"], reviewed=not exploratory,
                                required_kinds={"answer", "checkpoint", "memory_support", "memory_recall"},
                                provisional=exploratory and getattr(args, "check_examples", False))
        calibration["labels_sha256"] = digest(labels)
        calibration["reviewer"] = labels.get("reviewer", "")
        (output / "calibration.json").write_text(json.dumps(calibration, ensure_ascii=False, indent=2), encoding="utf-8")
        if calibration["status"] != "complete" and not exploratory:
            return save({"status": "incomplete", "reason": "Judge calibration did not pass", "calibration": calibration,
                    "usage": summarize(judge_rows, rates), "promotion_status": "incomplete"})
        import random
        order = [(case, arm, trial) for case in cases for trial in range(1, args.trials + 1) for arm in config["arms"]]
        random.Random(config["seed"]).shuffle(order)
        for case, arm, trial in order:
            if should_stop is not None and should_stop():
                break
            rows, replies, actions, durations = [], [], [], []
            capture = ProbeCapture(case)
            home = root / arm / str(trial) / case["id"]
            configured = settings(home, arm)
            def build(configured=configured, rows=rows, actions=actions, case=case):
                configured.ensure_home()
                client = make_client(configured)
                app = Waku(configured, client=client)
                tracer = Tracer(configured)
                def record(row):
                    record_usage(row, rows)
                    tracer.record_call(row)
                # Waku's single accounting owner captures actual stage identity.
                owner = app.client
                while not isinstance(owner, UsageClient):
                    owner = owner.client
                owner.record = record
                app.client = LimitedClient(app.client)
                app.memory.client = app.client
                if app.compactor:
                    app.compactor.client = app.client
                app.tools._tools = {k: v for k, v in app.tools._tools.items() if k in ("save_note", "manage_memory")}
                def action():
                    # A receipt belongs to the environment after execution;
                    # asking the model to invent the fixture receipt is not a task.
                    actions.append(case["old"])
                    return case["old"]
                app.tools.register(Tool("record_action", "Record one local fixture action.",
                    {"type": "object", "properties": {}}, action))
                app.tools.register(Tool("read_fixture", "Read a synthetic local log.", {"type": "object", "properties": {}},
                                        lambda: "x" * (case["output_kib"] * 1024)))
                return app
            app = None
            error = None
            try:
                app = build()
                app.session.start_new("primary-project")
                for step in expand(case):
                    if calls[0] >= args.max_calls or (should_stop is not None and should_stop()):
                        raise RuntimeError("Live call allowance exhausted")
                    if step["op"] == "restart":
                        app.close()
                        app.conn.close()
                        app = build()
                        app.session.switch(step["session"])
                    elif step["op"] == "switch":
                        app.session.switch(step["session"])
                    else:
                        capture.user_message(app.session.session_id, step["message"])
                        started = time.perf_counter()
                        try:
                            reply = app.respond(step["message"], observer=capture.observer(app), source="v5-live")
                        finally:
                            durations.append(time.perf_counter() - started)
                        replies.append({"message": step["message"], "reply": reply.reply})
            except Exception as exc:
                error = type(exc).__name__
            finally:
                if app is not None:
                    capture.finish(app, actions)
                    try:
                        app.close()
                    except Exception as exc:
                        error = error or type(exc).__name__
                    finally:
                        try:
                            app.conn.close()
                        except Exception as exc:
                            error = error or type(exc).__name__
            evidence = [case["current"]]
            if case["family"] in ("corrections", "forgetting"):
                evidence.append(f'Superseded or forgotten value, never assert as current: {case["old"]}')
            if case["family"] == "isolation":
                evidence.append("Project Z port 9999 belongs to a different session and must not answer this task.")
            item = {"id": f'{case["id"]}/{arm}/{trial}', "task": case["question"],
                    "evidence": {"authoritative_facts": evidence, "user_messages": capture.inputs,
                                 "final_memory_snapshot": (capture.memory or {}).get("snapshot")},
                    "reply": replies[-1]["reply"] if replies else "", "receipts": capture.executions}
            blinded, _ = blind([item], config["seed"])
            verdict = None
            probes = capture.report()
            if not error and calls[0] < args.max_calls:
                try:
                    verdict = grade(judge, args.judge_model, blinded[0])
                except Exception as exc:
                    error = type(exc).__name__
            elif not error:
                error = "CallAllowanceExhausted"
            if not error:
                grade_probes(probes, judge, args.judge_model)
                if probe_status(probes) == "incomplete":
                    error = "ProbeCoverageIncomplete"
            result = {"id": case["id"], "arm": arm, "trial": trial, "family": case["family"],
                      "split": case["split"], "probes": probes, "probe_metrics": metrics(probes),
                      "configuration": f"V5-{arm}", "turns": case["turns"], "turn_seconds": durations,
                      "status": "failed" if error else "complete", "error_type": error,
                      "replies": replies, "actual_actions": actions, "verdict": verdict, "usage": summarize(rows, rates)}
            result["judge_input"] = blinded[0]
            expected_actions = [case["old"]] if case["family"] == "tools" else []
            result["action_check"] = actions == expected_actions
            result["task_success"] = (bool(verdict["task_success"]) and not verdict["stale_assertion"]
                                      and not verdict["unsupported_assertion"] and result["action_check"]
                                      and probe_status(probes) == "complete" if verdict and not error else None)
            results.append(result)
            all_rows.extend(rows)
            with (output / "runs.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f'{len(results)}/{len(order)} {item["id"]} {result["status"]}', flush=True)
            if calls[0] >= args.max_calls:
                break
        from evals.context.quality import aggregate, promotion, second_provider_status
        final_source = source_snapshot()
        secondary, secondary_error = None, None
        if getattr(args, "second_provider", None):
            try:
                secondary = json.loads(args.second_provider.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                secondary_error = type(exc).__name__
        report = {"schema_version": 3, "runner": "live-exploratory" if exploratory else "live",
                "experiment": config["experiment"], "manifest_sha256": digest(config),
                "source": source, "source_end": final_source, "source_stable": source == final_source,
                "provider": args.provider, "models": {"answer": args.model, "small": args.small_model, "judge": args.judge_model},
                "rates": [{"provider": p, "model": m, **r} for (p, m), r in rates.items()],
                "status": "complete" if len(results) == len(order) and all(not r["error_type"] for r in results) else "incomplete",
                "trials": args.trials, "expected_runs": len(order), "actual_runs": len(results), "cases": results,
                "calibration": calibration, "usage": summarize(all_rows + judge_rows, rates),
                "quality_status": "complete" if not exploratory and len(results) == len(order) and all(r["verdict"] and not r["error_type"] for r in results) else "incomplete",
                "second_provider": second_provider_status(secondary, args.provider),
                "second_provider_evidence": secondary,
                "second_provider_error": secondary_error,
                "limits": ["Independent second-provider verification remains required before promotion.",
                           "Call allowance counts client requests; explicit adapter retries can add SDK invocations."]}
        report.update(aggregate(results, [(c["id"], f"V5-{a}", t) for c, a, t in order]))
        report["promotion_status"] = promotion(report)
        return save(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--exploratory", action="store_true", help="Allow provisional judging; never supplies release evidence")
    parser.add_argument("--case", dest="case_ids", action="append", help="Run a named case from the selected split")
    parser.add_argument("--split", choices=("development", "reserved", "all"), default="reserved")
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--small-model")
    parser.add_argument("--judge-model")
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--rates", type=Path, help="Optional rates per million tokens with source and checked_at")
    parser.add_argument("--second-provider", type=Path, help="A separate provider's completed compatibility report")
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--output", type=Path, default=Path("eval-results/v5-live"))
    args = parser.parse_args()
    if not 1 <= args.trials <= 5:
        parser.error("trials must be 1..5")
    if not args.live:
        print(json.dumps(plan(args.split, args.trials), indent=2))
        return 0
    if not all((args.provider, args.model, args.small_model, args.judge_model, args.calibration, args.max_calls)) or args.max_calls < 1:
        parser.error("Live execution requires all model IDs, reviewed calibration and a positive max-calls allowance")
    report = execute(args)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
