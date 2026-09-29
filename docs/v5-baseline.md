# V5: combined evaluation and observability

Measured on Windows with Python 3.13.15 on 2026-09-29. V4 was complete before
this work began. V5 supplies combined comparisons, attributed model usage and
dashboard evidence. **Live release acceptance remains incomplete.** Defaults
remain `budget` context, `legacy` memory and `legacy` retrieval.

## What changed

One accounting wrapper sits below Waku's request guards and records each SDK
invocation. Answer, retrieval gate, compaction, consolidation, quick reply and
graph calls retain stage, provider/model, session/turn, duration, request hash,
cache counters and failure identity. Explicit adapter retries count separately;
SDK-internal HTTP retries do not. A request rejected before dispatch adds no
invocation. Stream finalization records once, including partial or missing usage.
Graph worker threads inherit the turn's attribution without sharing mutations.

The existing Ops and Memory views show context estimates, checkpoint revisions
and validity, delivered evidence IDs, failures, stage counts and imported
comparison summaries. Runtime and judge usage have separate totals. Missing
usage remains unknown, and dollars require explicit price provenance. Older
pricing charts still show estimates. Independent legacy arenas and external
subprocesses are outside the Waku-client accounting boundary.

The evaluation modules add blinded semantic grading, reviewed-label calibration,
paired scenario uncertainty and release checks. Live execution is explicit,
uses disposable stores and exposes only local fixture tools. It saves final
replies, actual action receipts, verdicts and raw model-call rows. Labels supplied
by the implementation are proposed labels; they are not independent calibration.
The live runner has offline contract checks and a partial DeepSeek Flash pilot. A V5
acceptance follow-up adds snapshots and checks after each published compaction
and at final memory state; the original offline measurements below are unchanged.

## Frozen comparison

The manifest is [v5_manifest.json](../evals/context/v5_manifest.json). It freezes
the existing 36-case bank: 24 development and 12 reserved cases, six families,
four arms and five repetitions. The seed is 20260929; capacity is 32,768.
Fixture SHA-256: `bab4c5fd9911bf3692681a1bd4725cade9c14018059a53910dd5427d03ceea1f`.
Historical V1 B still means `budget`; these labels belong to V5.

| Arm | Context | Memory | Retrieval |
|---|---|---|---|
| V5-A | window | legacy | legacy |
| V5-B | compact | legacy | legacy |
| V5-C | window | lifecycle | selective |
| V5-D | compact | lifecycle | selective |

All **720 scenario runs and 32,640 turns** completed their scripted checks.
Each arm has 180 runs and 8,160 turns. No critical scripted checks failed in
correction, forgetting, isolation or tool-outcome families. This establishes
execution of the fixture contract; replies and extraction are scripted and
therefore cannot establish task success or learned memory quality.

| Arm | Client calls | Estimated total input | Local turn median | Local turn p95 |
|---|---:|---:|---:|---:|
| A | 18,000 | 144,178,310 | 11.3 ms | 17.2 ms |
| B | 18,770 | 100,609,685 | 41.8 ms | 71.5 ms |
| C | 17,870 | 99,196,550 | 46.0 ms | 143.6 ms |
| D | 18,600 | 108,490,425 | 77.5 ms | 190.4 ms |

D uses **24.8% less estimated input than A**, but 3.3% more calls and a higher
local median latency. C has the lowest estimated input in this run; combining
compaction with lifecycle memory does not automatically reduce total overhead.
Byte-based input estimates are not provider token measurements. Model tokens,
runtime dollars, judge dollars and task-success rates remain unmeasured.
Local timing includes concurrent development/test activity and is diagnostic.

The primary D-minus-A mean input difference is -198,266 estimated tokens per
scenario, with a paired 95% bootstrap interval of [-287,499, -105,625]. The
method resamples scenario clusters within families and keeps all five repeated
scripts together. Repetitions are not independent model samples. The task-success
interval is null, with 180 missing D/A trial pairs; it is not a zero improvement.

The original full matrix began at `e9f4dd2`. Its older runner captured the source
snapshot at completion, while later observability/evaluation edits were underway.
That report's `source` is a completion snapshot, not proof of an unchanged
execution checkout. This provenance limitation is preserved rather than relabelled.
The runner now records start/end snapshots and `source_stable`. A final smoke run
at `e595906` completed **48/48** short scenario runs (12 fixtures, all four arms)
with `source_stable=true`. It verifies the final implementation, not a second
720-run performance measurement.

## Verification and release status

The original isolated deterministic run passed **1215 checks**, with 63 skips for
API access, optional extras or platform requirements. Ruff, all six bundled skill
validations, public configuration-example consistency and documentation checks
passed. The strict gate retained `incomplete` because live coverage was not run.

Targeted checks cover missing/partial/zero usage, explicit retries, preflight
rejections, response parsing, streaming, cache arithmetic, judge separation,
blind payloads, invalid calibration labels, fixed coverage and median intervals.
Compatibility checks cover migration interruption/retry, preserved records,
concurrent session isolation, restart and disabling/re-enabling all three
policies without reviving suppressed facts.

Browser checks used the actual dashboard with disposable synthetic state:
Ops and Memory, light/dark themes, 1440- and 1100-pixel widths, navigation,
empty evidence and invalid comparison reports. No page errors were observed.
The preview loads no user configuration and sends no model requests.

The strict release gate reports **quality incomplete** when live judge coverage
or the V5 comparison evidence is missing. It cannot promote a scripted result,
partial fixture subset, incomplete calibration or a same-provider smoke report.
Critical failures override average improvements. Full live acceptance requires
five trials across the entire frozen matrix plus calibrated judging and a
separate provider's reserved compatibility run. Only a partial live pilot has run.
The semantic harness now grades final answers, each captured checkpoint, stored
facts and explicit required-fact recall. This capability has deterministic tests;
its live judge quality remains uncalibrated. V5 is not declared release-complete,
and the approved six-version plan does not define a V6 milestone.

### Acceptance follow-up

The follow-up's full isolated run passed **1239 checks**, with 63 skips and no
failures. Ruff, skill validation, configuration-example consistency and rulebook
checks passed. The strict gate stayed `incomplete` because no real provider
evaluation was requested. This adds 24 deterministic cases to the original V5
suite; it does not change the historical 720-run performance measurements.

`evals/context/probes.py` listens to the existing `compaction_completed` observer.
It immediately copies the published revision, covered user evidence and actual
local action receipts. Future corrections cannot relabel earlier checkpoints.
The final snapshot enumerates visible facts with a 200-record bound; an overflow
is incomplete, never a truncated passing sample. All arms share the evaluator's
input log, including window/legacy runs without canonical message rows.

Every snapshot is graded after runtime measurement. Checkpoint retention,
stored-fact supportedness, required-fact recall and consolidation-only
supportedness have explicit numerators and denominators. An empty store with a
required remembered fact fails recall. A zero denominator stays null. Correct
final wording cannot compensate for failed checkpoint or memory checks.
The published SQLite checkpoint inventory must match observed and captured
revisions. Snapshot failures are recorded without changing runtime behavior.

The live report uses schema version 3 and probe schema version 2. Reviewed calibration must cover successful
and failing answer, checkpoint, memory-support and memory-recall cases. Proposed
labels remain unreviewed. Startup failures, missing judgments and exact allowance
exhaustion produce persisted incomplete reports. Local action tools generate
receipts after execution; the model no longer has to guess the expected receipt.

`evals/context/acceptance.py` validates raw rows, calibration verdicts, unchanged
source snapshots and the embedded second-provider report. Display summaries
cannot override stale claims, repeated actions, failed critical tasks or missing
probes. It recomputes paired metrics for all cases and separately for reserved
cases. Durations must cover every declared turn. The quality-improvement route
does not require the token-efficiency metric used by the alternative route.
Reports from the older schema lack this evidence and remain incomplete.

An optional eight-case hybrid ranking experiment is separately frozen in
[hybrid_cases.json](../evals/retrieval/hybrid_cases.json). It accepts externally
computed vectors with model/source metadata, filters ineligible IDs before
fusion, and reports recall and unknown-query false positives. No vectors were
supplied: the recorded result is **unavailable**, and quality is incomplete.
It adds no embedding dependency or production retrieval path. Synthetic vectors
only test fusion mechanics; they cannot support a semantic-quality claim.

## Reproduce

Use the repository Python environment. On Windows it is
`.venv/Scripts/python.exe`; no real dotenv file is needed for these commands.

```bash
python -m evals.offline
python -m ruff check waku evals scripts
python -m evals.context.matrix --split all --trials 5 --output eval-results/context-v5-new.json
python -m evals.context.live --split all --trials 5
python -m evals.retrieval.hybrid --split all --output eval-results/v5-hybrid.json
python -m waku.ops.release_gate --strict --comparison eval-results/context-v5-new.json --output eval-results/v5-gate
```

The live command above prints a plan. It reads no credentials and makes no calls.
An existing partial matrix file is preserved; choose a new output filename to
rerun. Raw local results are under `eval-results/`, which is ignored by Git.

For an explicitly configured live run, the required arguments are `--live`,
`--provider`, `--model`, `--small-model`, `--judge-model`, `--calibration`,
`--max-calls` and a new `--output` directory. Provide credentials in that process
environment; dotenv discovery is disabled. The allowance limits client requests,
not internal SDK HTTP retries or a monetary amount. The Flash pilot below uses
the exploratory path. Review and copy the proposed calibration JSON before use;
its `reviewed=false` deliberately prevents release calibration.

Optional `--rates` accepts a JSON array. Each entry identifies `provider`, `model`,
`source`, ISO-date `checked_at`, and numeric `input`/`output` prices per million
tokens; `cached_input` and `cache_creation` are required when those usages occur.
The report retains this provenance. Optional `--second-provider` accepts the
other provider's live report; coverage and critical outcomes are checked.

For a small development pilot, `python -m evals.context.deepseek_pilot --live`
uses `deepseek-flash` with thinking disabled and a default CNY 5 allowance.
It reads only `DEEPSEEK_API_KEY` from the process environment. Without `--live`,
it prints a plan without reading credentials. The default selects six short
development cases across all four arms; repeat `--case ID` to select others.
Choose a fresh `--output` directory for each run.

The pilot disables SDK retries and redirects and uses a 90-second SDK timeout.
It logs only the exception type when a request fails and stops before starting
another scenario. Before each request, it reserves
the full advertised context plus maximum output at the official peak prices
checked on 2026-09-29. Provider usage releases unused reserves using peak prices;
cache discounts require consistent provider hit/miss counters. A transport error
or missing usage stops further paid calls.
`spend.json` records CNY separately from the existing USD ledger, and
`deepseek-usage.jsonl` retains the provider's cache counts. Prices must be
rechecked before reusing this dated guard. Balance changes may include other
activity on the same account.

The underlying live runner supports `--exploratory` and repeated `--case ID`.
Exploratory runs use provisional judge opinions and retain incomplete calibration,
quality and promotion status. They cannot supply release evidence.

Sequential batches share `--budget-ledger PATH` and the same `--budget-cny`
allowance. The journal flushes each reservation before dispatch, releases it
exactly once after valid usage, and retains unknown requests after interruption.
An OS lock prevents concurrent writers. The ledger rejects changed allowances,
changed rates and malformed records. A new campaign needs its own ledger path.
`--check-examples` measures agreement with proposed labels without claiming
independent review or completed calibration.

Judges now receive evaluator-captured tool results, including memory saves,
updates, searches and deletions. Arguments alone do not prove execution. Error
results remain visible as failed evidence. Structured runs verify original
result bytes and hashes; window runs capture the same completion events without
inventing persistence IDs. Checkpoint evidence excludes future and other-session
actions. Memory grading projects only subject/content while reports retain
storage metadata. Raw judge inputs are saved for auditing disagreements.

The Flash pilot requests JSON output for judge calls. The rubric defines each
boolean independently, including missing required facts and unsupported action
claims. `--rejudge REPORT.json` scores saved version-3 exploratory evidence in a
new output directory without replaying runtime or tools. It preserves previous
judgments, original report hashes, separate judge usage and scoring-source
snapshots. Rejudging cannot supply release evidence or repair missing execution.

The `covered-dialogue-v1` evidence contract adds complete covered message roles
and source IDs to checkpoint judgments. Assistant text proves that a reply was
given; it does not prove an external action succeeded. Final memory probes also
retain the observed dialogue. A deterministic guard rejects literal frozen
forgotten values in answers, current facts and post-deletion checkpoints, even
when the model calls them historical. It does not detect paraphrases. The
fixture action description now names the requested action without exposing its
expected receipt. Repeated `--arm` flags select explicit exploratory policies.

To show a completed report in a selected dashboard, run
`python -m evals.context.publish REPORT.json --home PATH_TO_SELECTED_WAKU_HOME`.
This replaces only `comparison_report.json` in that explicitly selected home.
It does not switch policies or remove memory. No result has been imported into
the user's runtime during this work.

## DeepSeek Flash pilot, 2026-09-29

Two explicit runs used `deepseek-flash` for answers, gates, memory extraction
and provisional judging, with thinking disabled. The six short development
families cover constraints, tool receipts, corrections, forgetting, retrieval
and session isolation. Each case has eight user turns. All data and tool actions
were synthetic, and memory lived in disposable stores.

| Measurement | Initial pilot | Forgetting follow-up |
|---|---:|---:|
| Source commit | `dab49ed` | `b87295b` |
| Source unchanged during run | Yes | Yes |
| Provider requests attempted | 211 | 85 |
| Responses with measured usage | 210 | 85 |
| Scenarios with final answers and verdicts | 9 | 4 |
| Scenarios with complete probe grading | 8 | 4 |
| User turns completed | 76 | 32 |
| Checkpoints published | 0 | 0 |

The initial request failure stopped further paid calls. Its original harness
still emitted failed rows for the remaining scenarios; those rows are not
completed coverage. One earlier scenario had a malformed probe verdict. The
follow-up stops before starting another scenario after transport failure,
retains only safe exception diagnostics, and uses a 90-second SDK timeout.
Both runs disabled automatic retries. Their combined conservative charge,
including a full-context reserve for the unknown failed request, is CNY 2.762012,
below the CNY 5 allowance. This reserve is not an invoice.

The 295 measured responses used 258,162 input and 10,375 output tokens; 156,160
input tokens hit the provider cache. Using the official off-peak prices checked
on 2026-09-29 gives **CNY 0.1466252 estimated cost**, excluding the failed request's
unknown usage. Account balance observations lagged the measured calls, so their
immediate deltas do not establish the final bill. Prices and the original
provider usage counters are retained with the local artifacts.

A later balance query returned CNY 24.82, compared with CNY 24.97 before the
first run. The observed CNY 0.15 account change is consistent with the measured
usage estimate, but may also include unrelated account activity.

The pilot found evaluation defects that prevent a credible policy ranking:

- Fact grading sometimes treated `scope` and `source` metadata as unsupported
  user claims, despite reading them from an actual stored-memory snapshot.
- Final-answer evidence included fixture action receipts but omitted memory-tool
  execution receipts, causing inconsistent judgments about saving and deleting.
- One judge response did not satisfy the strict response schema.

All four forgetting runs ended with an empty fact store and no repeated deleted
code in the final answer. The provisional judge still disagreed about deletion
claims. These observations support an evidence-payload and calibration follow-up;
they do not establish calibrated task-success rates. No checkpoint was published,
so this pilot does not measure compaction retention. Reserved cases, repeated
trials and another provider remain untested.

Local reports are `eval-results/deepseek-flash-pilot-20260929/report.json` and
`eval-results/deepseek-flash-forget-20260929/report.json`. Their SHA-256 digests are
`360221b9be321990bdc264eee59927114cf6396854ee9bfaf45f4b2b5e849e43` and
`79188207a881cd8659eb38417f98f5ab998389bd8cc6c6f7f2a1a9f21416a6b2`.
The combined local summary is `eval-results/deepseek-flash-summary-20260929.json`.
Raw reports stay outside Git. Calibration, quality and promotion remain incomplete.

The final isolated suite passed **1251 checks**, with 63 skips. Ruff, the skills
validator and generated environment-template checks passed. The strict release
gate retained `quality incomplete` because full live acceptance is still missing.

## Evidence repair and long-dialogue follow-up, 2026-09-29

The follow-up executed 43 runtime scenario runs and 800 user turns using
`deepseek-flash` with thinking disabled. It completed the six short development
cases across A-D, four 32-turn cases across A-D, and three focused 32-turn D runs.
Two additional judge-only passes reused the short run's saved evidence. No user
task or tool was replayed by those scoring passes. The runtime source and scoring
source were stable within each batch; their hashes remain in the raw reports.

| Batch | Runtime runs | User turns | Provider calls | Result |
|---|---:|---:|---:|---|
| Short development cases | 24 | 192 | 547 | All conversations finished; one initial judge JSON response failed |
| First judge-only pass | 0 | 0 | 85 | All 24 rows scored; 20 provisional passes |
| Four long development cases | 16 | 512 | 1,232 | All conversations finished; 21 checkpoints published; one probe verdict was invalid |
| Final judge-only pass | 0 | 0 | 85 | All 24 rows scored; 21 provisional passes |
| Focused D verification | 3 | 96 | 233 | Seven checkpoints published; two tasks passed, correction recall failed |

All **2,182 provider calls** returned measured usage. They used 2,385,833 input
tokens, including 1,377,144 cache hits, and 72,741 output tokens. The recorded
official off-peak prices give **CNY 1.32719588 estimated spend**. The shared budget
journal settled CNY 2.65439176 at peak prices, with no unresolved reservations,
below the CNY 5 cap. Balance observations changed from CNY 24.82 before the
campaign to CNY 23.53 afterwards; billing lag and unrelated account activity
prevent treating the immediate delta as the invoice.

The final rubric matched all 15 proposed examples in both regrading passes.
These examples were not independently reviewed. The rubric and evidence evolved
between batches, and free-text judgments still varied. Neither the 21/24 short
score nor the earlier long-run scores establish release quality. Initial long
checkpoint scoring lacked full assistant-message evidence; the final focused
runs captured that evidence. Earlier artifacts were preserved, not rewritten.

### Observed failures and retained behavior

- B (`compact/legacy/legacy`) repeated the forgotten synthetic address in its
  final answer and all three post-deletion checkpoints. The judge initially
  excused the answer as historical context. The new deterministic disclosure
  check rejects it. A, C and D did not disclose that value in this long case.
- D retained the corrected budget of 350 in its actual memory store but failed
  to retrieve it for the final question in both long attempts. Its later
  checkpoint also omitted the current requirement. The next runtime fix should
  trace retrieval decisions and evidence delivery after correction and compaction.
- C's window-only configuration lost the earlier budget constraint in the long
  run. D's focused constraint run returned the correct limit and passed all
  three checkpoint checks. D's focused forgetting run kept memory empty,
  disclosed no address and passed both checkpoint checks.
- Stored facts included unsupported claims about tool availability, and a
  legacy fact stated 512 fixture characters when the receipt contained 1,024.
  These are concrete consolidation-quality failures. Some other memory scores
  still reflect judge disagreement about filler-log descriptions.
- The long tool case exposed a vague fixture-action description and confusion
  between an action receipt and an unrelated log's unverified status. The
  description now names the requested action. This change was not validated by
  a fresh tool-case run in this campaign; its regression check is offline only.

The long-run runtime totals below include gate, answer, consolidation and
compaction calls, but exclude judges. They are observations from one attempt
per case, including failed tasks, not evidence of a quality-preserving saving.

| Policy | Runtime input tokens | Runtime output tokens | Runtime calls | Checkpoints |
|---|---:|---:|---:|---:|
| A | 333,897 | 5,083 | 288 | 0 |
| B | 319,501 | 12,284 | 300 | 12 |
| C | 261,830 | 6,164 | 284 | 0 |
| D | 318,692 | 10,220 | 294 | 9 |

The local summary is `eval-results/flash-evidence-summary-20260929.json`. It
records report paths, SHA-256 hashes, source commits, raw token totals, literal
disclosure checks and remaining limitations. The budget journal is
`eval-results/flash-evidence-campaign-20260929.jsonl`. All reports and usage
ledgers remain ignored by Git; no result was imported into the user's runtime.

The final isolated suite passed **1274 checks**, with 63 skips. Ruff, skill
validation and the generated environment-template check passed. Full live
acceptance remains incomplete: corrected-fact recall, consolidation quality,
judge review, reserved coverage and a second provider still need work. Defaults
remain unchanged, and no 96-turn or full-matrix live acceptance claim is made.

## Policy rollback

Select `WAKU_CONTEXT_POLICY=budget`, `WAKU_MEMORY_POLICY=legacy` and
`WAKU_RETRIEVAL_POLICY=legacy`, then restart. Existing archives and execution
receipts remain in place. Suppression remains authoritative even when lifecycle
writes or selective retrieval are disabled. This is a policy rollback, not a
schema downgrade; old releases unaware of lifecycle metadata are not guaranteed
to preserve the same suppression behavior.
