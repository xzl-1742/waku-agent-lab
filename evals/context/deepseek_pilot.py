"""Explicit, budgeted Flash pilot; credentials come only from the process.

Prices and model limits were checked against the official DeepSeek pricing
page on 2026-09-29. The guard uses peak prices and ignores cache discounts.
Each request reserves the full 1M-token context plus its maximum output before
sending. Missing usage or a transport error stops all further paid requests.
"""

import argparse
import json
import os
import threading
import urllib.request
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

MODEL = "deepseek-flash"
BASE = "https://api.deepseek.com"
PRICING = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
CONTEXT = 1048576
MILLION = Decimal(1000000)


class PilotStopped(RuntimeError):
    pass


class Budget:
    def __init__(self, limit, max_calls):
        self.limit = Decimal(str(limit))
        if not self.limit.is_finite() or self.limit <= 0 or max_calls < 1:
            raise ValueError("Budget and call allowance must be positive")
        self.max_calls = max_calls
        self.upper = Decimal(0)
        self.calls = 0
        self.stopped = False
        self.lock = threading.Lock()

    def reserve(self, model, max_tokens):
        if model != MODEL or type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
            raise PilotStopped("Pilot model or output limit changed")
        reservation = (Decimal(CONTEXT) * 2 + max_tokens * 8) / MILLION
        with self.lock:
            if self.stopped or self.calls >= self.max_calls or self.upper + reservation > self.limit:
                self.stopped = True
                raise PilotStopped("Pilot budget or call allowance exhausted")
            self.upper += reservation
            self.calls += 1
        return reservation

    def settle(self, reservation, usage):
        incoming = getattr(usage, "prompt_tokens", None)
        outgoing = getattr(usage, "completion_tokens", None)
        if any(type(v) is not int or v < 0 for v in (incoming, outgoing)):
            self.stopped = True
            raise PilotStopped("Provider usage missing; reservation retained")
        charged = (Decimal(incoming) * 2 + outgoing * 8) / MILLION
        with self.lock:
            if incoming > CONTEXT or charged > reservation:
                self.stopped = True
                raise PilotStopped("Provider usage exceeded the reserved model limits")
            self.upper += charged - reservation


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

    sdk = openai.OpenAI(api_key=key, base_url=BASE, max_retries=0, timeout=30,
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
        except Exception:
            budget.stopped = True
            # Do not print provider bodies or request headers on a failure.
            raise PilotStopped("DeepSeek request failed; further paid requests stopped") from None

    class Client(OpenAICompatClient):
        def __init__(self):
            self.messages = SimpleNamespace(create=self._create)

        def _call(self, kwargs, **extra):
            request = {**kwargs, **extra}
            request["max_tokens"] = request.pop("max_completion_tokens")
            request["extra_body"] = {"thinking": {"type": "disabled"}}
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
    budget = Budget(args.budget_cny, args.max_calls)
    before = balance(key)
    if Decimal(before) < budget.limit:
        raise PilotStopped("Requested allowance exceeds the available balance")
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
        output=args.output, split="development", trials=1, max_calls=args.max_calls, case_ids=selected)
    report = None
    try:
        report = live.execute(settings, client_factory=make_client)
        return report
    finally:
        if close:
            close[1]()
        spend = {"model": MODEL, "thinking": "disabled", "sdk_retries": 0,
            "budget_cny": str(budget.limit), "conservative_spend_cny": str(budget.upper),
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--budget-cny", type=str, default="5")
    parser.add_argument("--max-calls", type=int, default=650)
    parser.add_argument("--case", dest="case_ids", action="append")
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
