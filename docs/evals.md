# Evals and tracing

The LLM-Ops pillar: two kinds of eval, a release gate that needs both, and a
trace of every turn.

## Two kinds of eval, never mixed

*"Did it create the right calendar event?"* is a unit test: 0 or 1, and no
model judges it. *"Was the reply helpful?"* is a judged score with a threshold.
Conflating the two is the most common eval mistake, so here they are separate
suites you can diff.

```bash
make eval          # deterministic: "did the right tool fire?" — 0 or 1, no model judges it
make eval-judge    # LLM-as-judge: "was the reply helpful?" — a scored %, needs a key
make gate          # the release gate: deterministic must pass 100%, judge must clear threshold
```

Deterministic tests are plain pytest in
[`evals/deterministic/`](../evals/deterministic); judged ones use DeepEval in
[`evals/judge/`](../evals/judge). CI runs the deterministic tier on every PR.
The judge tier needs an API key. `make gate` explicitly enables live evaluation
and strict coverage checks; it can spend API credits.

`python -m evals.offline` runs the deterministic suite in a fresh Python process.
The launcher clears application settings and credentials, redirects the home to a
temporary directory, and installs guards before importing Waku or pytest plugins.
Python children inherit the guards. External DNS, TCP and UDP calls fail;
loopback fixture servers remain available. Native subprocesses must be mocked
by their tests because the Python guard is not an operating-system sandbox.
Dotenv discovery stays disabled except in the test of a synthetic scratch file.
Direct pytest runs also install guards before collecting test modules.
Live tests require `WAKU_RUN_LIVE_EVALS=1`; the offline launcher clears this flag.

`python -m waku.ops.release_gate` runs offline checks and reports quality as
`incomplete` unless required live suites complete. `--strict` returns exit code 2
for incomplete coverage; failures return 1. `--live` explicitly allows loading
credentials and running paid judge calls. Missing credentials, empty suites,
all-skipped suites and partial live skips cannot open the strict gate.
Each suite records `complete`, `skipped` or `failed`, with counts and elapsed time.

Reports go to `eval-results/eval_report.json` and `eval_runs.jsonl` by default.
Pass `--output .waku` (or your configured agent home) to show the report in the
dashboard's **Ops** tab. Reports retain the legacy dashboard fields.

## Catching bugs

The history regressions cover zero and negative `WAKU_HISTORY_TURNS` values.
Zero excludes earlier exchanges from the model prompt and session reload.
The database retains those exchanges. Negative values fail configuration validation.

When you catch a bug by using the thing live, you fix it AND add a
deterministic case so it can never come back. A real example from this repo:
the agent didn't know the current *time* and asked for it before scheduling
"in 30 minutes". The fix is in [`session.py`](../waku/runtime/session.py), and
[`test_working_memory.py`](../evals/deterministic/test_working_memory.py) locks
it in. Run `make gate` → green → the eval history records the run.

## Spend is permanent

Every LLM call's tokens are appended to `.waku/usage.jsonl`, an append-only
ledger that a demo reset never wipes. The **Ops** tab shows the all-time cost,
tokens, and a per-day / per-provider breakdown (dollar cost is estimated from
tokens, which are the ground truth). So the number on screen is your real
running total, not a per-session guess.

## Tracing is always on

Every turn appends readable lines to `.waku/traces/<date>.jsonl` with zero
setup — a trace is just "what happened, in order." For span-waterfall views:

```bash
pip install -e '.[tracing]'
make trace                                            # Phoenix at localhost:6006
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 make run
```

Langfuse cloud speaks the same OTel toggle.
