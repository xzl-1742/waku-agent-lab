"""Explicit, budgeted Flash pilot; credentials come only from the process.

Prices and model limits were checked against the official DeepSeek pricing
page on 2026-09-29. The guard uses peak prices and verified cache counters.
Each request reserves the full 1M-token context plus its maximum output before
sending. Missing usage or a transport error stops all further paid requests.
"""

import argparse
import json
import os
import urllib.request
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from evals.context.pilot_budget import CONTEXT, MODEL, Budget, PilotStopped

BASE = "https://api.deepseek.com"
PRICING = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"


def balance(key):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(BASE + "/user/balance", headers={"Authorization": "Bearer " + key})
    with opener.open(request, timeout=20) as response:
        data = json.load(response)
    values = [r for r in data["balance_infos"] if r["currency"] == "CNY"]
    if not data["is_available"] or len(values) != 1:
        raise PilotStopped("Available CNY balance could not be verified")
    return values[0]["total_balance"]


def factory(key, budget, output):
    import openai

    from waku.loop.models import OpenAICompatClient
    from waku.ops.accounting import sdk_call

    sdk = openai.OpenAI(api_key=key, base_url=BASE, max_retries=0, timeout=90,
        http_client=openai.DefaultHttpxClient(follow_redirects=False, trust_env=False))

    def invoke(**request):
        reservation = budget.reserve(request["model"], request["max_tokens"])
        try:
            response = sdk.chat.completions.create(**request)
            budget.settle(reservation, response.usage)
            row = {"model": response.model, "usage": response.usage.model_dump(),
                   "cost_upper_cny": str(budget.upper)}
            with (output / "deepseek-usage.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            if budget.calls % 10 == 0:
                print(f"Flash requests: {budget.calls}; conservative spend CNY {budget.upper:.4f}", flush=True)
            return response
        except Exception as exc:
            budget.stopped = True
            with (output / "deepseek-errors.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"request_number": budget.calls, "error_type": type(exc).__name__,
                    "reservation_cny": str(reservation.amount), "cost_upper_cny": str(budget.upper)}) + "\n")
            # Do not print provider bodies or request headers on a failure.
            raise PilotStopped("DeepSeek request failed; further paid requests stopped") from None

    class Client(OpenAICompatClient):
        def __init__(self):
            self.messages = SimpleNamespace(create=self._create)

        def _call(self, kwargs, **extra):
            from evals.context.quality import RUBRIC

            request = {**kwargs, **extra}
            request["max_tokens"] = request.pop("max_completion_tokens")
            request["extra_body"] = {"thinking": {"type": "disabled"}}
            if not request.get("tools") and any(isinstance(m.get("content"), str) and m["content"].startswith(RUBRIC)
                                               for m in request["messages"]):
                request["response_format"] = {"type": "json_object"}
            return sdk_call(invoke, request)

    return lambda settings: Client(), sdk.close


def run(args):
    if not args.live:
        raise ValueError("Live execution must be explicit")
    from evals.context import live
    from evals.context.fixtures import load_cases

    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("Set DEEPSEEK_API_KEY in this process; dotenv loading is disabled")
    if args.output.exists():
        raise ValueError("Choose a new output directory")
    before = balance(key)
    if Decimal(before) < Decimal(args.budget_cny):
        raise PilotStopped("Requested allowance exceeds the available balance")
    budget = Budget(args.budget_cny, args.max_calls, getattr(args, "budget_ledger", None),
                    allow_increase=getattr(args, "increase_budget", False))
    # live.execute disables dotenv before calling this lazy factory.
    close = []
    def make_client(settings):
        if not close:
            create, cleanup = factory(key, budget, args.output)
            close.extend([create, cleanup])
        return close[0](settings)
    selected = args.case_ids or [c["id"] for c in load_cases() if c["split"] == "development" and c["turns"] == 8]
    settings = SimpleNamespace(live=True, exploratory=True, provider="deepseek", model=MODEL,
        small_model=MODEL, judge_model=MODEL, calibration=Path(__file__).with_name("calibration.example.json"),
        output=args.output, split="development", trials=getattr(args, "trials", 1), max_calls=args.max_calls, case_ids=selected,
        check_examples=getattr(args, "check_examples", False), arms=getattr(args, "arms", None))
    report = None
    try:
        if getattr(args, "rejudge", None):
            from evals.context.rejudge import execute
            report = execute(args.rejudge, args.output, settings, make_client, lambda: budget.stopped)
        else:
            report = live.execute(settings, client_factory=make_client, should_stop=lambda: budget.stopped)
        return report
    finally:
        if close:
            close[1]()
        spend = {"model": MODEL, "thinking": "disabled", "judge_json_mode": True, "sdk_retries": 0, "timeout_seconds": 90,
            "budget_cny": str(budget.limit), "conservative_spend_cny": str(budget.upper),
            "budget_ledger": str(getattr(args, "budget_ledger", None)), "prior_spend_cny": str(budget.initial_upper),
            "batch_conservative_spend_cny": str(budget.upper - budget.initial_upper),
            "unresolved_reservations": len(budget.pending),
            "requests": budget.calls, "stopped": budget.stopped, "balance_before_cny": before,
            "pricing_source": PRICING, "pricing_checked_at": "2026-09-29",
            "input_peak_cny_per_million": 2, "output_peak_cny_per_million": 8,
            "reservation_input_tokens": CONTEXT,
            "limits": ["Peak rates bound spend only while the recorded official prices remain valid.",
                       "Balance changes can include unrelated activity on the same account."]}
        try:
            after = balance(key)
            spend.update(balance_after_cny=after, balance_change_cny=str(Decimal(before) - Decimal(after)))
        except Exception as exc:
            spend["balance_error_type"] = type(exc).__name__
        if args.output.exists():
            (args.output / "spend.json").write_text(json.dumps(spend, indent=2), encoding="utf-8")
            if report is not None:
                report["pilot"] = spend
                (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(spend), flush=True)
        budget.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--budget-cny", type=str, default="5")
    parser.add_argument("--increase-budget", action="store_true", help="Append an explicitly approved allowance increase; retain prior spend")
    parser.add_argument("--trials", type=int, choices=range(1, 6), default=1, help="Repetitions per selected scenario and arm")
    parser.add_argument("--max-calls", type=int, default=650)
    parser.add_argument("--budget-ledger", type=Path, default=Path("eval-results/deepseek-flash-budget.jsonl"),
                        help="Share this durable allowance across sequential batches")
    parser.add_argument("--check-examples", action="store_true", help="Measure provisional label agreement without claiming reviewed calibration")
    parser.add_argument("--rejudge", type=Path, help="Regrade saved synthetic evidence without repeating runtime or tools")
    parser.add_argument("--case", dest="case_ids", action="append")
    parser.add_argument("--arm", dest="arms", choices=list("ABCD"), action="append", help="Explicit exploratory policy subset")
    parser.add_argument("--output", type=Path, default=Path("eval-results/deepseek-flash-pilot"))
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({"mode": "plan", "model": MODEL, "budget_cny": args.budget_cny,
                          "credentials_loaded": False, "quality_status": "incomplete"}))
        return 0
    try:
        result = run(args)
    except Exception as exc:
        print(json.dumps({"status": "incomplete", "error_type": type(exc).__name__}))
        return 2
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
