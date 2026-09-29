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

## Context and memory baseline (V0)

`python -m evals.context.runner --split all --output eval-results/context-v0.json`
runs 36 synthetic multi-turn scenarios through the production session, tool loop
and SQLite stores. The launcher installs offline guards before importing Waku.
Each scenario gets a fresh home, a fixed UTC prompt clock and configuration A.
The default split runs 24 development cases; `--split reserved` selects the 12
frozen cases. Six families each contribute four development and two reserved cases.

The fixture bank varies 8, 32 and 96 user turns, evidence position, 1/16/64 KiB
tool results, corrections, deletion, Chinese pronouns and restart/session switches.
Outcome checks inspect stored facts, transcript rows and action receipts. Input
probes expose omitted constraints and stale facts still present in history.
These probes describe model input availability; scripted answers do not establish
task success, retrieval-gate quality or a guarantee against repeated external actions.
Consolidation runs on its normal schedule with empty scripted extraction results.

The JSON report records fixture and expanded-turn hashes, prompt templates,
model labels, explicit settings, trial, Python/platform details and a source manifest.
The manifest hashes allowlisted code and bundled skills even without a Git commit.
Each client/tool call measures its actual execution boundary with a monotonic clock.
Client-call counts exclude hidden SDK retries. Missing and synthetic token usage
and costs remain `null`; real-model quality remains `incomplete`.
Configuration A retains the window policy; V1 adds B with context budgets and
recoverable tool outputs. V2 adds B2 with persistent checkpoints. C and D remain unavailable.
The runner supports scripted execution only; paid scenario comparisons remain
separate work. The existing live judge suite is enabled only by an explicit command.

The reference snapshot pins Pi to a commit and stores short paraphrases of the
official Claude Code documentation in `evals/context/references.json`.

## Context budgets and A/B comparisons (V1 and V2)

Run each policy against the same frozen data:

```bash
python -m evals.context.runner --configuration A --split all --output eval-results/context-v1-A.json
python -m evals.context.runner --configuration B --split all --output eval-results/context-v1-B.json
python -m evals.context.runner --configuration B2 --split all --output eval-results/context-v2-B2.json
```

All runs use a 32,768-token test capacity, 8,192 output reserve and 1,024 safety
margin for main calls. `--capacity` changes the test capacity for both model roles.
Reports include per-request estimates, model output allowances, tool-schema hashes,
pairing checks, recoverable artifact checks and source manifests. Estimate totals
include answer, gate, consolidation and any compaction calls. A budget violation in A means its
estimated request would exceed B's configured budget, not a measured provider rejection.
B can reject an oversized helper request without dispatching it; rejected requests
remain visible in the report. B2 enables session compaction with an
evidence-only scripted summary. All three policies use the same frozen
fixtures. B2 reports include compaction calls, timing and prompt hashes;
real-model retention and cost remain unmeasured.

For normal Waku use, `WAKU_CONTEXT_POLICY=budget` is the default. `window` restores
the original comparison policy. `WAKU_CONTEXT_WINDOW` and `WAKU_SMALL_CONTEXT_WINDOW`
set explicit capacities; zero selects the conservative 32,768 fallback. Capacities
apply to their configured model IDs, and a shared ID takes the smaller capacity.
`WAKU_CONTEXT_SAFETY` defaults to 1,024. `WAKU_TOOL_OUTPUT_BYTES` defaults to 4,096
and must be at least 1,024. The fallback is a local policy, not a verified model limit.

An oversized required request stops with a clear error. The legacy memory
consolidator leaves an oversized backlog unprocessed. The optional
[V3 lifecycle](v3-baseline.md) selects bounded session batches and preserves
suppression across retrieval, checkpoint reuse and restart.
Canonical records and full result files add disk usage. V1 does not delete runtime
data, summarize old conversation or claim that forgotten information is absent
from old transcripts. The V0 quality limitations still apply.

## Selective retrieval comparison (V4)

The [V4 comparison](v4-baseline.md) uses a separate, frozen 24-case bank with
16 development cases and eight reserved cases. Run
`python -m evals.retrieval.runner --split all --output eval-results/retrieval-v4.json`.
The report separates search recall, delivered recall and recall after a bounded
recovery search. It also records forbidden evidence, evidence budgets, source
ordering, scripted gate misses and serialized-byte relevance share.

Both policies use scripted gates and real isolated SQLite stores. The selective
candidate removes common-word false positives, but reserved average recall does
not improve. Paraphrase and old-value lookup misses stay visible. A complete
execution means critical invariants held, not that all relevant evidence was
found. Answer assertions, learned gate quality, provider tokens and cost remain
unmeasured. V0's long-context fixtures and V5's combined C/D labels stay separate.

## Combined comparison (V5)

`python -m evals.context.matrix --split all --trials 5` runs the frozen four-arm
offline matrix. V5-A is window/legacy/legacy, V5-B compact/legacy/legacy,
V5-C window/lifecycle/selective, and V5-D compact/lifecycle/selective. Historical
V1 B still means budget. Repeated scripts measure execution and local timing;
they do not measure model task success. See [the V5 report](v5-baseline.md).

`python -m evals.context.live` prints a plan without loading configuration or
credentials. Execution requires explicit `--live`, provider/model IDs, reviewed
calibration cases and a client-call allowance. It uses disposable SQLite stores
and local fixture tools. It disables dotenv discovery. Optional `--rates` reads
dated price provenance; absent usage or prices leave costs unknown. The harness
stores raw call rows separately from blind verdicts and checks actual action
receipts. `--second-provider` validates a separate provider's reserved smoke report.
Incomplete coverage, source changes or missing evidence cannot promote defaults.

The optional `python -m evals.retrieval.hybrid` experiment uses a separate frozen
eight-case bank and externally supplied vectors. Without them it reports
unavailable. It compares ranking, not production answer quality.

## Catching bugs

The history regressions cover zero and negative `WAKU_HISTORY_TURNS` values.
Zero excludes earlier exchanges from the model prompt and session reload.
The database retains those exchanges. Negative values fail configuration validation.

When you catch a bug by using the thing live, you fix it AND add a
deterministic case so it can never come back. A real example from this repo:
the agent didn't know the current *time* and asked for it before scheduling
"in 30 minutes". The fix is in [`session.py`](../waku/runtime/session.py), and
[`test_working_memory.py`](../evals/deterministic/test_working_memory.py) locks
it in. The gate records each run in its output directory.

## Spend is permanent

Waku's model client appends usage to `.waku/usage.jsonl`, an append-only ledger
that a demo reset never wipes. It covers answer, retrieval gate, compaction,
consolidation and graph/helper stages through that client. The installed judge
wrappers use a separate judge scope. Each SDK invocation records model, provider,
request hash, duration, cache usage and session/turn identity when available.
Explicit adapter retries count separately; internal SDK HTTP retries do not.
Guard rejections before dispatch record no paid invocation.

The **Ops** and **Memory** views show stage counts, measured subtotals, unknown
usage, checkpoints and evidence IDs. Missing usage or unsupported price provenance
leaves strict totals unknown. The older pricing charts remain estimates and cannot
establish complete cost. Independent legacy arenas and external subprocesses are
outside the Waku-client ledger contract.

## Tracing is always on

Every turn appends readable lines to `.waku/traces/<date>.jsonl` with zero
setup — a trace is just "what happened, in order." For span-waterfall views:

```bash
pip install -e '.[tracing]'
make trace                                            # Phoenix at localhost:6006
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 make run
```

Langfuse cloud speaks the same OTel toggle.
