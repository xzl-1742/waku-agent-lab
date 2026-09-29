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
The live runner has been exercised with injected offline clients only. A V5
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
separate provider's reserved compatibility run. Real execution has not been run.
The semantic harness now grades final answers, each captured checkpoint, stored
facts and explicit required-fact recall. This capability has deterministic tests;
its live judge quality remains unmeasured. V5 is not declared release-complete,
and the approved six-version plan does not define a V6 milestone.

### Acceptance follow-up

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

The live report uses schema version 2. Reviewed calibration must cover successful
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
not internal SDK HTTP retries or a monetary amount. This command has not been run
against a real provider. Review and copy the proposed calibration JSON before use;
its `reviewed=false` deliberately prevents release calibration.

Optional `--rates` accepts a JSON array. Each entry identifies `provider`, `model`,
`source`, ISO-date `checked_at`, and numeric `input`/`output` prices per million
tokens; `cached_input` and `cache_creation` are required when those usages occur.
The report retains this provenance. Optional `--second-provider` accepts the
other provider's live report; coverage and critical outcomes are checked.

To show a completed report in a selected dashboard, run
`python -m evals.context.publish REPORT.json --home PATH_TO_SELECTED_WAKU_HOME`.
This replaces only `comparison_report.json` in that explicitly selected home.
It does not switch policies or remove memory. No result has been imported into
the user's runtime during this work.

## Policy rollback

Select `WAKU_CONTEXT_POLICY=budget`, `WAKU_MEMORY_POLICY=legacy` and
`WAKU_RETRIEVAL_POLICY=legacy`, then restart. Existing archives and execution
receipts remain in place. Suppression remains authoritative even when lifecycle
writes or selective retrieval are disabled. This is a policy rollback, not a
schema downgrade; old releases unaware of lifecycle metadata are not guaranteed
to preserve the same suppression behavior.
