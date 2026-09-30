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
  checkpoint also omitted the current requirement. The 2026-09-30 follow-up below
  fixes a reproducible retrieval miss and records the live evidence delivery.
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

## Corrected-value retrieval repair, 2026-09-30

D answered the final 32-turn correction question with **350 units** after the
retrieval repair in `e67dab8`. This is one targeted live check, not full acceptance.
The deterministic regression reproduced eight failures before the repair:
revision-qualified searches, gate-error fallback, and delivery to the main
request after compaction, with and without a restart.

The lexical matcher previously counted `corrected budget` as two required terms.
The active fact contained `budget` but not `corrected`, so its 0.5 coverage fell
below the 0.6 threshold. Search now removes `corrected`, `updated` and `revised`
when another substantive term remains. Qualifier-only queries still require a
match. Scope, suppression, ranking thresholds and evidence budgets stay in force.
The gate prompt also requests memory for previously saved or corrected values
when recent context omits them. Earlier failed runs did not retain gate decisions,
so the lexical reproduction does not establish their exact live decision path.

The new live report records gate decisions and delivered IDs for each turn.
On turn 32, the gate requested `budget`, the initial search delivered only fact
2 with no omissions, and the answer cited that corrected fact. The delivered
payload used 208 estimated tokens against the 1,024-token evidence allowance.
The final answer and stored-fact checks passed; neither asserted 900 as current.

Both intermediate checkpoints still omitted the corrected budget. Their checks
failed, so the combined case result remains failed despite the correct final
answer. Lifecycle correction deliberately excludes earlier transcript sources;
the replacement remains in durable memory. Retaining that corrected requirement
in checkpoints needs separate work. This repair does not change the checkpoint
contract, relax its evaluator, or establish recall for other long conversations.

The batch made 77 measured provider calls: 72 runtime calls and five judge calls.
It used 87,276 input tokens, including 49,792 cache hits, and 1,802 output tokens.
The official Flash prices were rechecked on 2026-09-30. At peak prices, the batch
cost estimate is **CNY 0.09137568**. The existing CNY 5 campaign journal now records
CNY 2.74576744 conservatively, with no unresolved reservations. Immediate balance
observations both returned CNY 23.50; that observation is not an invoice.

The ignored local report is `eval-results/flash-correction-fix-20260930/report.json`.
Its SHA-256 is `19e8f482a103250568ae99d7b6c3f09b731162b8cf2668a36e3b276635dfdb75`.
Source snapshots matched before and after execution. The report preserves failed
checkpoint verdicts and leaves live acceptance incomplete. All stores and tool
outputs were synthetic and disposable; the user's runtime was not modified.

The full isolated suite passed 1,286 checks with 63 skips. Ruff, skill validation
and the environment-template check passed. The strict release gate still reports
incomplete live coverage; no promotion or default-policy change is justified.

## Checkpoint and extraction repair, 2026-09-30

The corrected value now survives both checkpoint revisions in the targeted
32-turn Flash run. The final answer returned 350 units, and neither checkpoint
asserted 900. This closes the observed value-retention defect. The runtime
fixes are `d7fe508` and `9b9c43f`; `c5dd1bc` adds checkpoint-time version evidence.

Correction writes retain a link to the mutation turn. Checkpoint reads project
only the active replacement, preserving the archived conversation. Every
revision pins that current value and rechecks scope, generation, provenance and
the existing byte bound. Repeated correction, deletion, restart and unrelated
memory invalidation have deterministic regressions. A completed response clears
its mutation-turn identity so later standalone edits cannot inherit that turn.

Both extraction policies now reject generated facts or episodes that are not
complete user quotations. Lifecycle extraction requires exactly one matching
user citation and records it per memory, rather than attributing the whole batch.
Regressions reject invented log lengths, assistant-only claims, false subject
labels and quotes with negation removed. These guarantees concern automatic
extraction, not the truth of user statements or every explicit model tool write.
The stricter policy deliberately gives up automatic paraphrasing and can leave
an invalid batch pending for retry.

### Final offline checks

The final suite passed **1,301 checks**, with 63 skips. Ruff, skill validation
and the generated environment-template check passed. Four 32-turn development
cases (correction, forgetting, constraints and tools) completed on all four arms
with three scripted repetitions: **48 runs and 1,536 user turns**. The declared
critical invariant checks reported no failures. Source snapshots stayed stable.

| Scripted arm | Runs | Estimated input tokens | Model calls |
|---|---:|---:|---:|
| A | 12 | 6,952,935 | 855 |
| B | 12 | 5,082,495 | 891 |
| C | 12 | 4,857,489 | 843 |
| D | 12 | 5,294,571 | 873 |

D used 23.85% fewer estimated input tokens than A in this selected scripted
matrix. These are serialized-byte estimates, not provider tokens or measured
billing savings. Repeated scripted outputs are not independent model samples.
The matrix has only one scenario per family, so its collapsed bootstrap
intervals do not establish statistical certainty. Local runtime increased.

The report is `eval-results/memory-repair-scripted-20260930.json`, with SHA-256
`c9d597162c43b3b4d467a8e0a9441b1c1a01d471577926a1ff9ea200279fb35f`.

### Live observations and scoring boundary

The fresh D run made 78 measured Flash calls: 73 runtime calls and five judges.
It consumed 94,213 input tokens (53,376 cache hits) and 1,957 output tokens.
The final answer and both stored-fact checks passed. Both raw checkpoint
snapshots contain 350 and omit 900. Runtime input was 76,276 tokens versus
70,948 in the preceding retrieval-only run; this repair makes no real cost-saving
claim from that pair of single trials.

The initial checkpoint judge accepted one revision and rejected the other
because the summary named current fact 2 while the update receipt named old
fact 1. The runtime had correctly created replacement fact 2. A judge-only
follow-up confirmed the evidence gap: it rejected both numbered references
because the saved checkpoint evidence lacked that version mapping. The original
report remains failed; no verdict was overwritten. The new observer now captures
`id`, `supersedes`, content and source boundary at publication, with a regression
showing that later corrections cannot rewrite an earlier snapshot. This added
capture needed a fresh live run at that stage; the repeated cohort below supplies
that evidence without backfilling older reports.

The first scoring follow-up stopped after eight calibration calls because its
call allowance was too small. The completed follow-up used 20 calls and matched
14 of 15 unreviewed calibration examples. The mismatch concerned overlapping
stale/unsupported labels for a forgotten value. Neither follow-up establishes
reviewed calibration or full acceptance.

The runtime report is `eval-results/flash-memory-repair-20260930/report.json`,
with SHA-256 `6652abe2f5931ff1bd44ee870c03ac97c636e78f377676fefeb88b36eb0b5bbf`.
The completed scoring report is
`eval-results/flash-memory-repair-regrade-complete-20260930/report.json`.
All 106 calls in this repair session returned usage. Their peak-rate cost bound
is CNY 0.14809736; the verified off-peak rates estimate CNY 0.07404868. The shared
campaign journal now settles CNY 2.89386480 conservatively with zero unresolved
reservations. The latest balance observation is CNY 23.35, subject to billing lag.

The original CNY 5 allowance could not reserve the next full-context answer call
after that settled total. The repeated cohort below used an explicitly approved
CNY 8 cumulative allowance. Full live acceptance, independent calibration review
and a second provider remain incomplete. The default policies stay unchanged.

### Project description supported by these results

- Extended an open-source Python agent with SQLite memory versions, scoped
  retrieval, suppression, provenance-checked checkpoints and restart recovery.
- Added deterministic source-grounding checks to automatic memory extraction
  and preserved correction values across repeated compactions without restoring
  superseded or deleted context.
- Verified 1,301 offline checks and a 48-run scripted comparison, and traced a
  32-turn DeepSeek Flash correction case through storage, retrieval and two
  checkpoint revisions. Recorded real usage and retained failed judge evidence.

These claims describe engineering and observed tests. They do not claim a full
live pass, production reliability, independent statistical validation or a
23.85% reduction in real API cost.

## Repeated Flash verification, 2026-09-30

The frozen D cohort completed **13 runs and 480 user turns**. Final-answer
judgments passed **12/13**, while combined answer, action and intermediate-state
checks passed **9/13**. These results verify selected development scenarios;
they do not establish full live acceptance. All original failures remain in
[the committed observation summary](../evals/context/results/flash-repair-20260930.json).

The runtime fixes remained at source commit
`7847cf2858673389c2a226c5d82045562546cb2f` throughout both batches. Four 32-turn
cases ran three times each, followed by one 96-turn correction case. Each run
used fresh disposable state and DeepSeek Flash with thinking disabled. Source
snapshots stayed stable, all 1,178 model calls returned usage, and no call failed.

### Measured outcomes

| Development case | Runs | Turns per run | Final-answer passes | Combined passes | Checkpoint passes |
|---|---:|---:|---:|---:|---:|
| Correction, `correction-02` | 3 | 32 | 3/3 | 3/3 | 6/6 |
| Forgetting, `forget-02` | 3 | 32 | 3/3 | 2/3 | 5/6 |
| Constraint, `constraint-02` | 3 | 32 | 3/3 | 2/3 | 9/9 |
| Tool receipt and restart, `tool-02` | 3 | 32 | 2/3 | 2/3 | 8/8 |
| Long correction, `correction-03` | 1 | 96 | 1/1 | 0/1 | 8/9 |
| Total | 13 | 480 total | 12/13 | 9/13 | 36/38 |

All four correction runs returned the current value. Each of their 15 published
checkpoints retained the replacement and its version mapping. The 96-turn case
preserved version 8 through nine compactions. All three forgetting runs ended
with empty memory and passed both the final-answer judgment and literal deleted
value check. All three tool runs executed the export exactly once across restart.
These observations describe the selected fixtures, not general reliability rates.

Stored-fact support passed 10/10 judgments, and required memory recall passed
4/4. The isolated offline suite passed **1,302 checks**, with 63 skips and no
failures. Ruff, skill validation and the environment-template check passed.
The strict release gate reports `incomplete` because its separate live suite was
not requested. These exploratory Flash batches do not replace that suite or
the full comparison and independent calibration requirements.

### Four retained failures

- `forget-02`, trial 3, failed one checkpoint judgment. The judge claimed that
  arithmetic citations were wrong and deletion constraints were missing. The
  captured input contains those source rows, declares no required constraints
  and does not disclose the deleted address. Assistant inspection found a
  disagreement with the supplied evidence; the raw failed verdict remains.
- `constraint-02`, trial 2, made an unexpected `record_action` call. The action
  check correctly failed even though the final answer and checkpoints passed.
  The fixture tool describes an action as requested in every family, which may
  encourage selection in a constraint-only task. This contract and model
  selection problem remains visible in the result.
- `tool-02`, trial 2, failed the final-answer judgment. The export was not
  repeated and the reply retained receipt B23, but it mixed unrelated arithmetic
  into the answer and described execution metadata as synthetic log content.
  The judge also disputed captured receipt evidence. Successful recovery alone
  does not establish answer quality, so the failed result remains.
- `correction-03` failed its first checkpoint judgment because the judge claimed
  arithmetic steps 4-11 were absent. The actual judge input contains question
  and answer pairs 15/16 through 29/30. All nine checkpoints retain version 8.
  Assistant inspection records the disagreement without changing the verdict.

The provisional calibration check matched 14/15 labels. Its remaining mismatch
concerns stale and unsupported labels for a forgotten value. The calibration
labels have no independent review, and this cohort uses one provider. Both
`quality_status` and `promotion_status` remain `incomplete`; the default policies
remain unchanged. No repeated judging was used to replace a failed outcome.

### Usage and reproduction

The batches made 1,098 runtime calls and 80 judge calls. Providers reported
1,456,957 input tokens and 36,044 output tokens. The peak-rate estimate for
these batches is **CNY 1.53694220**, using recorded cache usage. The shared
campaign journal settles CNY 4.43080700 with zero unresolved reservations under
the approved CNY 8 allowance. Account balance changes can lag billed usage;
they are not a substitute for the usage ledger. This cohort makes no claim of
improved live cost or latency relative to another policy.

The two original local reports are
`eval-results/flash-final-repeated-20260930/report.json` (SHA-256
`7aa2c3558f0afa18a6cf120de045f54f61cbda10781f4bad1463bab61d24783c`) and
`eval-results/flash-final-long96-20260930/report.json` (SHA-256
`5003f6521fdbecbd62300666f791422ef37a0c6cdd08e67c0c8ef795dbe620f9`).
The committed observation summary records source hashes, original verdicts,
per-case metrics, version evidence and inspection notes. It excludes account
balances and credentials; the full synthetic transcripts remain local.

With a process-level `DEEPSEEK_API_KEY`, a user can reproduce the selected scope
with the commands below. These commands make paid API calls. Both batches share
one journal and CNY 8 cumulative allowance; output directories must be new.
When increasing an existing journal's allowance, `--increase-budget` records
the explicitly authorized increase while retaining prior spend and reservations.

```sh
python -m evals.context.deepseek_pilot --live --budget-cny 8 --budget-ledger eval-results/repeated-flash-budget.jsonl --arm D --trials 3 --max-calls 1500 --check-examples --case correction-02 --case forget-02 --case constraint-02 --case tool-02 --output eval-results/repeated-flash
python -m evals.context.deepseek_pilot --live --budget-cny 8 --budget-ledger eval-results/repeated-flash-budget.jsonl --arm D --max-calls 350 --case correction-03 --output eval-results/long96-flash
```

## Policy rollback

Select `WAKU_CONTEXT_POLICY=budget`, `WAKU_MEMORY_POLICY=legacy` and
`WAKU_RETRIEVAL_POLICY=legacy`, then restart. Existing archives and execution
receipts remain in place. Suppression remains authoritative even when lifecycle
writes or selective retrieval are disabled. This is a policy rollback, not a
schema downgrade; old releases unaware of lifecycle metadata are not guaranteed
to preserve the same suppression behavior.
