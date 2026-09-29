# Context, memory and evaluation: six development versions

The proposed development sequence delivers reliable long conversations in six versions, V0 through V5.
V2 completes the first usable compaction milestone. V5 completes the combined context and memory release.
These labels identify development milestones; they do not change the package version.

The proposal was approved for V0 implementation on 2026-09-27. Performance targets have not been measured.
V0 implementation and offline verification are complete; [the baseline report](v0-baseline.md) records the results and unmeasured live quality.
V1 implementation was approved on 2026-09-28; [the V1 report](v1-baseline.md) records
the implemented behavior and frozen A/B results. V2 now implements opt-in
session compaction and offline B2 comparisons. Live summary quality remains
unmeasured. V3 and V4 now implement opt-in lifecycle memory and selective retrieval.
V5 supplies combined offline comparisons, attributed usage and live evaluation
entry points. Live release acceptance remains incomplete; see
[the V5 report](v5-baseline.md). This proposal still defines the remaining
quality and resource gates.

## 1. Outcomes and current evidence

The assistant should preserve task constraints across long conversations, resume work after a restart, apply corrections, and avoid recalling forgotten facts.
Evaluation should show whether each change improves task completion and what it costs in tokens and elapsed time.

Source inspection established the following starting conditions:

- `Session.build_system()` is missing from the current working copy, but `Waku._run_full_turn()` calls it. V0 restores the original method before measuring the baseline.
- The current history policy keeps 12 exchanges by default. It does not cap the total input tokens, and `history_turns=0` selects all history because Python interprets `[-0:]` that way.
- The loop inserts full tool results into the active conversation. Session history also includes tool arguments and output in a text summary.
- The retrieval gate receives the current user message without conversation history.
- `save_note` writes directly to SQLite, while consolidation uses the configured fact store. Fact management also coerces opaque IDs to integers.
- Consolidation reads all unconsolidated chat rows without a batch budget or a session filter. A fact has a coarse source label, but no reference to its supporting message.
- The release gate skips judge evaluation without a key and still prints `GATE OPEN`.

These findings come from static inspection. The existing status document's test counts are not fresh verification of this working copy.

## 2. Design references

The proposal borrows a few mechanisms and preserves Waku's small Python core.

| Reference | Mechanism to adapt | Waku application |
|---|---|---|
| [Pi compaction](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/compaction.md) | Pi keeps a recent message suffix and persists a summary with its retained boundary. | A session checkpoint records which messages its summary covers. |
| [Pi implementation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/compaction/compaction.ts) | Pi uses context estimates and valid message boundaries. | Every model request receives a budget check that preserves tool-call/result pairs. |
| [Claude Code context management](https://code.claude.com/docs/en/how-claude-code-works#when-context-fills-up) | Claude Code clears older tool outputs before summarizing and bounds repeated compaction attempts. | Cheap output reduction precedes model summarization, with bounded recovery. |
| [Claude Code memory](https://code.claude.com/docs/en/memory) | Claude Code separates persistent instructions from auto memory and loads memory details on demand. | Waku keeps rules separate from retrieved facts and bounds injected memory. |
| [Claude Code context reload](https://code.claude.com/docs/en/context-window) | Claude Code reloads persistent instructions after compaction. | Waku rebuilds current rules and settings instead of trusting the summary to preserve them. |
| [Anthropic agent evaluations](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | Agent evaluation distinguishes transcripts from outcomes and uses repeated trials. | Graders inspect stored results and constraints as well as answer quality. |

These references were consulted on 2026-09-25. V0 records the Pi commit and documentation snapshot used for implementation.
Claude Code behavior comes from official documentation; the proposal does not assume access to its private implementation.

## 3. Shared architecture

Each turn should assemble a bounded context, call the existing loop, and retain enough evidence to resume and evaluate the work.

```text
current request + recent messages + session checkpoint
    -> bounded memory query
    -> rules + checkpoint + recent messages + relevant memories + tools
    -> budget check
    -> existing model/tool loop
         -> persist tool outcome
         -> reduce large output if needed
         -> budget check before the next model call
    -> persist exchange
    -> consolidate eligible source messages in bounded batches
```

The design keeps three forms of information separate:

| Form | Purpose | Proposed persistence |
|---|---|---|
| Original records | The records explain what the user said and what tools actually did. | SQLite message and execution records retain source IDs; large outputs use local artifacts. |
| Session checkpoint | The checkpoint lets one task continue after compaction or restart. | A session-scoped record stores its summary, coverage boundary and revision. |
| Long-term memory | A memory carries useful facts or preferences across conversations. | The selected fact store remains authoritative; metadata records scope and evidence. |

Compression does not delete original messages. A generated checkpoint does not automatically become long-term memory.
Memory and tool output remain evidence with a stated source; summarization must not promote their embedded instructions into system rules.

The context builder gives current rules and the active request explicit positions.
It keeps task constraints and confirmed action outcomes outside disposable raw-output excerpts.
Each injected memory remains a data item with its source and scope, rather than an instruction appended without attribution.

### Proposed records

The final field names will be settled during implementation review. The following responsibilities are required:

- A `SessionCheckpoint` records the session ID, checkpoint revision, covered source boundary, retained boundary, structured summary, model/prompt version and usage.
- A `ToolExecution` records the session, turn and call IDs, tool name, arguments, completion status and a result reference. A pending record distinguishes an interrupted action from an action known to have succeeded.
- A memory record or compatible metadata sidecar records its backend ID, scope, evidence IDs, origin, update time and current validity. An explicit correction can point to the superseded memory.
- A consolidation batch records the source message IDs and a stable batch ID. Retrying the batch must not duplicate its committed facts.
- A suppression record prevents specified old evidence from recreating a forgotten memory. It retains minimal identifiers rather than a copy of the forgotten text.
- An evaluation result records the scenario/configuration versions, model IDs, trial, outcome checks, skips, failures, stage timings and usage.

SQLite migrations add fields or tables without clearing runtime data. Existing facts retain a global scope and an unknown historical evidence reference when no reliable source can be recovered.
The design must not invent provenance for old rows.

## 4. V0: restore a measurable baseline

V0 produces a working baseline and the evaluation contract for all later versions.

### Changes

1. Restore `Session.build_system()` from the repository's original baseline contents without reverting unrelated changes.
2. Validate history-window settings. Define zero as no prior exchanges and reject negative values, with deterministic regression cases.
3. Run the relevant existing offline tests and record pre-existing failures separately from new failures.
4. Establish isolated test setup before importing configuration: disable dotenv discovery, block network calls in offline tests, and direct all writes to a temporary home.
5. Define 36 synthetic multi-turn scenarios, with 24 development cases and 12 reserved evaluation cases, stratified across the six families in section 10.
6. Add complete/skipped/failed evaluation statuses. Local offline checks remain usable; a strict quality gate rejects missing required suites or entirely skipped live checks.
7. Record model IDs, prompts, fixture hashes, configuration, schema version and source revision for every experiment. A directory without commits uses an explicit file snapshot manifest.
8. Measure elapsed time around actual calls. Event notification duration is not a model or tool execution duration.

### Acceptance

- Offline regression tests for context assembly and the established tool loop pass.
- Offline runs prove that they neither load a user's `.env` nor reach a network service.
- A live evaluation without configured credentials reports an incomplete result, rather than claiming quality passed.
- The baseline report contains task outcomes, input/output tokens, model-call counts and stage timings when observed; missing observations remain marked missing.

V0 supplies the reproducible A configuration. Live baseline runs are budgeted separately and only begin when their credentials and spending are configured.

## 5. V1: bound context and tool output

V1 bounds each model request and records action results without using LLM summaries.

### Changes

1. Introduce a small context-budget policy under `waku/runtime/`. Include system instructions, memories, skills, tool schemas, history and pending messages in the input budget.
2. Resolve the configured model's context capacity and reserve output tokens plus a safety margin. Unknown model aliases require an explicit or conservative capacity, rather than an optimistic guess.
3. Prefer provider usage as calibration evidence. Estimate unmeasured additions, test Chinese/code/JSON inputs, and label estimates. Recompute after compression or edits invalidate earlier usage.
4. Apply checks before the first main-model call and after every completed tool batch. A long single user turn must receive the same protection as a long chat.
5. Bound model-visible tool output by retaining status, critical fields and an excerpt. Preserve the full result as a local artifact, with a bounded read action on an existing tool surface.
6. Persist tool executions and canonical message records needed for subsequent compaction. Keep role and tool-call identifiers intact.
7. Temporarily select a recent valid suffix when history exceeds the budget. If the current request and required material alone cannot fit, return a clear size error.

### Acceptance

- Deterministic cases cover long user messages, long tool output, multiple tool results, Chinese text and unknown model IDs.
- No assembled request exceeds the configured estimated budget without an explicit failure result. Live tests measure estimation error and provider rejections separately.
- Every retained tool result has its matching call, and an omitted output has a usable result reference.
- Short conversations keep the established behavior and require no additional summarization call.

V1 bounds input size, but it may still omit older task details. V2 addresses that loss.

### V1 implementation decisions

The `budget` policy is enabled by default; `window` retains configuration A for
comparison. An explicit main/small-model capacity overrides a conservative 32,768
token fallback. The fallback describes Waku's policy, not a verified provider limit.
Every request reserves its actual output allowance plus a configurable margin.
The dependency-free estimator counts UTF-8 JSON bytes plus framing overhead and
labels that count as an estimate. Observed usage can increase its calibration;
missing or synthetic usage cannot decrease the budget. Live calibration is unmeasured.

A shared client guard covers streaming, graph, gate and consolidation calls made
through Waku. The main loop can remove complete old exchanges and reduce tool
observations; direct helper calls fail before dispatch when they cannot fit.
The current user request, instructions and active tool-call/result groups stay
intact. A terminal budget or recording error must never trigger graph replay.

Two additive tables retain canonical messages and tool execution records alongside
the existing chat log. Each execution is recorded pending before the tool runs;
pending after interruption means unknown outcome, not permission to repeat it.
Full outputs use generated result IDs under the agent home. The existing
`manage_memory` tool gains a session-scoped `read_result` action with bounded
pagination. Oversized observations retain an excerpt, result reference, execution
state and selected outcome fields; free-form tool text is not proof of success.
Prompt history uses bounded observations while canonical records retain originals.

V1 tests compare A and B on the frozen V0 bank, with separate stress tests for
oversized inputs, multi-tool batches, Unicode, streaming, persistence failures and
session access. Scripted quality and token cost remain unmeasured.

## 6. V2: compact and resume conversations

V2 replaces old message omission with a persistent task checkpoint plus recent messages.

The implementation uses an opt-in `compact` context policy. `budget` remains
the V1 default, and `window` remains the frozen baseline. A checkpoint belongs
to one session and publishes its summary and source boundary in one SQLite
transaction. Each replacement names the prior revision. Failed or concurrent
summaries leave the published revision intact.

The summary uses the configured main model unless `WAKU_COMPACTION_MODEL`
selects another model on the same provider. Summarization has an independent
output limit and a bounded number of input chunks. Recent complete turns keep
their roles, tool identifiers and provider metadata. Saved result references
preserve access to large tool outputs. Interrupted executions stop resumption
with their recorded status; compaction never runs a tool.

Context-limit recovery retries only the rejected model request, once, after
compacting older completed turns. Recovery must produce a smaller request.
An oversized active turn stops with a useful error if no older history can
be compressed. The existing gateway locks also protect manual `/compact`.

### Changes

1. Select older messages at valid boundaries and generate a structured summary containing goals, user constraints, completed actions, decisions, unresolved items, next steps and source references.
2. Use the previous checkpoint together with newly covered original records. Retain explicit source coverage so repeated compaction does not silently skip previously retained messages.
3. Keep recent complete message groups verbatim. Never cut a tool result away from its call.
4. Store the new checkpoint and its boundary atomically only after validation. Empty, malformed or failed summaries do not replace the previous checkpoint.
5. Rebuild current rules and model settings after compaction. Load checkpoints when switching or resuming a session.
6. Bound the summarizer's own input and output. Split an oversized source span at valid boundaries rather than sending an oversized summarization request.
7. Make one controlled recovery attempt for a context-limit error. Stop if compaction cannot reduce the request enough; do not repeat the whole tool sequence.
8. Add a manual `/compact` action through the existing command surface and emit compaction started/completed/failed events.

The initial quality comparison pins a summary model. A separately configurable compaction model may use the existing provider/client; a cheaper model is promoted only after the retention evaluations pass.

### Acceptance

- Tests cover one and several compactions, failed summaries, session switching, restart, model-window changes and very large single turns.
- Summaries retain the expected constraints and completed-action references in the deterministic cases.
- A known completed action is not automatically replayed during context recovery.
- An interrupted external action with an unknown outcome is surfaced for reconciliation. The feature does not claim exactly-once execution for arbitrary external tools.
- Model trials measure downstream task completion and unsupported statements after compaction, rather than grading summary style alone.

V2 completes the first usable milestone: long conversations can continue from a checkpoint and resume after restart.

## 7. V3: make memory writes, corrections and forgetting consistent

V3 gives long-term memory a reliable lifecycle independently of retrieval improvements.

### V3 implementation decisions

`WAKU_MEMORY_POLICY=lifecycle` enables SQLite lifecycle writes and bounded
session extraction. The default remains `legacy` for the frozen comparisons.
Persisted validity and suppression rules remain enforced after disabling new
lifecycle writes. Remote stores keep ordinary CRUD with opaque IDs; requesting
SQLite lifecycle guarantees with a remote store fails explicitly.

Memory metadata separates global, project and session scope from the session
where a fact was learned. Explicit corrections create linked versions. Exact
normalized duplicates share one active record; similar wording never replaces
a different record. Batches record exact source IDs and hashes, and commit
their writes and processed markers in one SQLite transaction.

Suppression retains identifiers and hashes, excludes implicated source groups,
and invalidates earlier checkpoints using a persistent generation. Original
chat and result records remain intact. A same-turn correction or deletion ends
the tool batch with a deterministic acknowledgement before any further model
call. Readable exports refresh atomically before success is reported.

The initial compatibility policy is deliberately conservative: every correction
or deletion invalidates all earlier conversation context and checkpoints in the
home, all derived facts and episodes, and exact duplicate explicit values.
Unrelated explicit facts remain active. Pre-V3 data does not have enough
provenance to prove that an old summary is independent of a changed fact.
This costs task context; original rows and result files remain in the archive.
Content-free execution receipts remain available to discourage action replay.
Unresolved executions still block continuation, even when their text is excluded.

New inputs and tool observations receive exact normalized phrase filtering;
complete explicit replacement values remain eligible. This cannot identify all
paraphrases supplied again by external sources. Suppression is a context policy,
not erasure of archives, external services or a model's pretrained knowledge.
Turning the flag off retains enforcement once suppression has been recorded;
checking out an older binary that ignores these columns is not a safe rollback.

Lifecycle extraction sends at most one bounded session batch per invocation.
An exchange too large to fit remains pending with a visible blocked event.
The input cap bounds model requests, not the size of the local pending-row scan.
Home-scoped process and thread locks serialize turns, publication and memory
mutations; model calls hold that lock, so another gateway may wait or time out.

The initial evaluation labels are `V3-window` and `V3-compact`. Their metadata
identifies lifecycle policy and unchanged retrieval policy separately. V5's
combined C/D labels remain reserved until the retrieval work is implemented.

### Changes

1. Route explicit saves, consolidation, edits and deletes through the selected store and a shared policy layer. Preserve opaque backend IDs.
2. Add evidence IDs, source type, scope, validity and update metadata. Keep global, project and session scope separate from the session in which a fact was learned.
3. Add normalized exact deduplication and stable batch identifiers. Local writes and consolidation markers commit together; remote adapters use resumable batch records or report unsupported atomicity.
4. Consolidate bounded batches grouped by session, with a token limit. Only verified source batches become committed. A newer message arriving during extraction remains unprocessed for the next batch.
5. Preserve explicit correction links and stop retrieving superseded versions by default. Similar wording alone must not authorize replacement of a different fact.
6. Implement memory suppression across retrieval, consolidation, readable exports and active/checkpoint context views. Invalidate or rebuild affected checkpoints from eligible source records so old summaries do not reintroduce a forgotten fact.
7. Keep minimal suppression identifiers. Clearing original chats or other runtime records remains a separate explicitly authorized operation.

### Acceptance

- Tests exercise explicit writes and CRUD with integer and string IDs, plus configured backend conformance.
- Repeating an extraction batch does not create duplicate committed memories in supported adapters.
- An explicit correction produces one active current value, with traceable prior evidence.
- A forgotten fact stays out of retrieval and rebuilt context after consolidation, restart and checkpoint reload.
- The migration preserves existing records and can disable enhanced behavior without requiring table deletion.

The first enhanced lifecycle implementation targets SQLite. Existing remote backends retain their established capabilities; unsupported metadata or suppression guarantees must be reported explicitly and must not silently degrade into empty search results.

## 8. V4: improve retrieval and selective memory loading

V4 improves which memories reach the model and when they are loaded.

### V4 implementation decisions

`WAKU_RETRIEVAL_POLICY=selective` opts into a separate SQLite retrieval policy;
`legacy` remains the default for the existing comparisons and remote adapters.
Selective retrieval rejects unsupported remote stores explicitly. The lifecycle
and context policies remain independent, with lifecycle recommended for V3
correction and forgetting guarantees.

The gate receives the current message plus bounded eligible dialogue and a
valid checkpoint hint. It accepts only an exact decision schema. Invalid output
or an ordinary API failure triggers one bounded lexical fallback; terminal
budget and suppression failures propagate. Trace events distinguish deliberate
skips, malformed decisions, API failures, search failures and tool recovery.

Local matching uses a separate Unicode search normalization, whole words and Han
bigrams, plus limited English plural/`ing` matching. Scope and validity filter before ranking. Relevance precedes source
priority and freshness; ranking is an ordering rule, not a probability. The
initial implementation scans eligible SQLite rows with a bounded top-k heap.
Query length, match terms and returned material are bounded; database scan time
still grows with the store. No derived index or embedding dependency is added.

Initial evidence and tool searches return ID-bearing snippets under a serialized
token estimate budget. `manage_memory` gains opt-in `read` and `recent` actions;
detail pages recheck the whole record before slicing. A turn permits two tool
searches/recent requests and three detail pages. Empty keyword queries return
no matches; only an explicit episode-recency request selects recent events.

A separate frozen development/reserved fixture compares retrieval availability
under `V4-retrieval-control` and `V4-retrieval-candidate`. Gate replies are scripted;
context and parsing tests verify wiring, not learned pronoun interpretation.
The report separates search recall, delivered recall, recovery, evidence share
and stale/unsupported evidence from unmeasured answer assertions and model cost.
Paraphrase misses remain visible; hybrid retrieval stays a separately evaluated
optional experiment rather than a dependency added to make a synthetic score pass.

### Changes

1. Give the gate the current message, a bounded recent-dialogue excerpt and a bounded checkpoint/entity hint. Apply the same summarizer/gate input accounting used for main calls.
2. Validate the decision schema strictly. Distinguish a deliberate skip, an invalid decision and a retrieval failure in telemetry.
3. Improve Unicode and Chinese keyword coverage with deterministic normalization and bounded matching. Treat an empty query separately from a request for recent events.
4. Filter by scope and active validity before ranking. Apply relevance, freshness and source policy without presenting an uncalibrated confidence score as a probability.
5. Allocate a token budget to retrieved material as well as a result-count limit. Supply short entries with IDs and load details through the existing memory-search tool when needed.
6. Give the main model a bounded opportunity to call `manage_memory(search)` when the gate misses needed information. Record that recovery separately from initial retrieval.
7. Add an optional hybrid-search experiment only if the reserved tests show a material lexical-recall gap. Any embedding dependency stays behind an extra and contributes to cost accounting.

### Acceptance

- Cases cover pronouns, Chinese names within sentences, paraphrases, common words, contradictory facts, scope boundaries, stale data and questions with no known answer.
- Reports include gate false negatives, Recall@k, relevant-token share, recovery searches, stale assertions and unsupported assertions.
- Retrieval must preserve the V3 correction and forgetting guarantees.
- A more expensive search policy needs a measured quality gain; changing the database backend alone is not treated as improvement.

The implemented [V4 comparison](v4-baseline.md) passes its critical evidence
checks but does not improve reserved average recall. Paraphrase and old-value
queries still miss records. The optional hybrid experiment therefore needs a
new frozen comparison and remains V5 work. V4 does not promote selective
retrieval to the default or claim measured answer quality.

## 9. V5: compare, observe and release the combined system

V5 selects a measured configuration and packages the operational evidence needed to maintain it.

### V5 implementation decisions

The versioned V5 manifest defines A as window/legacy/legacy, B as
compact/legacy/legacy, C as window/lifecycle/selective and D as
compact/lifecycle/selective (context/write/retrieval). Historical V1 B and V2 B2
labels keep their existing meanings. The frozen 36-case bank supplies a shared
execution comparison; its scripted replies establish availability and state
checks, not learned task quality. Repeated deterministic trials measure coverage
and local timing, not independent model samples.

One accounting owner records SDK invocations, including explicit adapter retries,
below request guards and before response interpretation. SDK-internal HTTP
retries remain outside that boundary. Stage, model, provider, session, turn,
cache counters, failures and unmeasured usage remain visible. Judge spend stays
separate. Unknown usage or unsupported rates cannot become zero cost.

The primary paired comparison is D minus A, with B minus A and C minus A as
secondary comparisons. Uncertainty resamples scenarios within families while
retaining paired arms and repetitions. A failed critical scenario cannot be
hidden by mean improvement. Live trials, independent judge calibration and
second-provider evidence remain required for promotion; an offline run leaves
those fields incomplete. Defaults do not change on scripted evidence.

The existing Ops and Memory views show bounded trace projections, including
context occupancy estimates, compaction history, retrieved IDs and comparison
coverage. Turn identifiers prevent interleaved sessions from sharing evidence.
Compatibility cases cover restart, failed migration/retry, competing sessions
and disabling/re-enabling all three policies without resurrecting suppression.

V4 reserved cases are now regression data. Optional hybrid experiments use a
separate frozen fixture and remain outside the four primary arms. Synthetic
expansions or vectors can verify fusion mechanics but cannot demonstrate semantic
quality or justify a production default.

### Changes

1. Run the A/B/C/D comparisons in section 10 with fixed fixtures, prompts, models and store configuration.
2. Use code-based outcome checks where possible and a calibrated model judge for semantic assertions. Blind the judge to the candidate label.
3. Report all model usage, including gate decisions, compaction and consolidation. Separate judge expenditure from runtime cost. Record cached usage when the provider exposes it.
4. Show context occupancy, compaction history, memory evidence and evaluation results through the existing Ops and Memory views. Follow the existing frontend design rules and browser verification workflow.
5. Exercise restart, checkpoint invalidation, migration failure, concurrent sessions and feature disablement in an isolated environment.
6. Update architecture, commands, configuration examples and evaluations documentation. Test compatibility before promoting the new policy to the default.

### Acceptance

- Required offline suites pass, and required live suites are complete rather than skipped.
- Reserved scenarios meet the predeclared quality gates; failed critical cases cannot be hidden by an improved average.
- The release report includes trial counts, uncertainty, failures, latency, total runtime tokens and judge expenditure.
- The previous policy remains selectable, and migrations preserve runtime records. The rollback procedure does not silently resurrect superseded or forgotten facts.

V5 completes the proposed scope. A release is postponed if it cannot demonstrate benefit within the declared quality and resource limits.

## 10. Evaluation contract

### Dataset and experiments

The initial 36 scenarios cover six families with six scenarios each: task constraints, tool outcomes, factual corrections, forgetting/unknown answers, Chinese/pronoun retrieval, and session/project isolation.
Each family assigns four cases to development and two to reserved evaluation. Developers tune on the 24 development cases and freeze the 12 reserved cases before comparing candidates.

Fixtures vary conversation length, output size and relevant-information position. Representative lengths are 8, 32 and 96 user turns, with tool outputs of roughly 1, 16 and 64 KiB; cases use selected combinations rather than an exhaustive Cartesian product.
The suite forces compaction with small test budgets and also checks the configured real-model budget.
Fixtures include facts that should persist, values that were superseded, actions already completed, unknown answers and exact expected side effects.

| Configuration | Context policy | Memory policy |
|---|---|---|
| A | The restored original window policy runs. | The original memory policy runs. |
| B | The new context policy runs. | The original memory policy runs. |
| C | The restored original window policy runs. | The new memory policy runs. |
| D | The new context policy runs. | The new memory policy runs. |

Every run uses a fresh disposable store, a fixed clock where relevant and recorded configuration.
Correctness fixes shared across the experiment are recorded explicitly. Legacy-memory comparisons use synthetic isolated data rather than undoing a user's suppression records.
An unavailable policy combination is reported as unavailable, not replaced silently.

Development trials use at least three repetitions for selected changed cases. Final trials target five repetitions for all 36 scenarios and all four configurations: 720 scenario runs, each containing multiple messages.
V0 measures per-scenario calls and tokens to estimate this budget before a live run. A smaller affordable run is labelled exploratory and reports its reduced sample size.
Before promotion, a second supported model/provider receives a compatibility smoke suite, and opaque memory IDs receive adapter tests.

### Metrics and gates

| Metric | Definition or required interpretation |
|---|---|
| Task success | A grader verifies the requested final state and task constraints. |
| Constraint retention | A grader checks required facts and constraints after each compaction and at task completion. |
| Retrieval recall | A grader compares retrieved evidence IDs against expected relevant evidence at a declared k. |
| Memory extraction quality | A grader measures supported stored facts against required facts and rejects invented facts. |
| Stale/unsupported assertion rate | A grader finds claims that use superseded evidence or lack support. |
| Repeated side effects | A grader checks actual action records, rather than trusting a success sentence. |
| Runtime cost | The report includes all agent-model calls and optional embedding/reranking costs. |
| Latency | The report includes median, tail latency and stage durations measured around real work. |
| Coverage | The report distinguishes passed, failed, skipped, unavailable and incomplete checks. |

All deterministic invariants must pass. Critical reserved cases for forgotten information, explicit corrections, session isolation and repeated side effects must have zero observed violations in the acceptance runs; this is a test result, not a universal guarantee.

The quality and efficiency objectives below are provisional. V0 calibrates and freezes them before candidate tuning, recording any change:

- The combined policy should improve long-horizon task success by at least 10 percentage points over A, or reduce median runtime tokens per successful long task by at least 20% when A is already near the suite's quality ceiling.
- Short-task success should not fall more than 3 percentage points, and median short-task latency should not increase more than 10% without an explicit documented tradeoff.
- Runtime token comparisons include summarization and consolidation. Failed tasks and tail latency remain visible alongside successful-task cost.

The initial fixture bank is small. The report should include paired uncertainty estimates and flag inconclusive comparisons; it should not claim statistical assurance from a few trials.
When a result is inconclusive, expand scenarios or repetitions before making a quality claim.

## 11. Code placement and delivery boundaries

| Concern | Existing locations | Proposed additions or changes |
|---|---|---|
| Context assembly | `waku/app.py`, `waku/runtime/session.py`, `waku/config.py` | Small `runtime/context_budget.py` and `runtime/compaction.py` modules can hold pure policy and summarization logic. |
| Model/tool loop | `waku/loop/agent.py`, `waku/tools/registry.py` | Add a narrow preparation/checkpoint interface and retain the current tool contract where possible. |
| Durable context | `waku/db.py` | Add versioned session checkpoints and execution/message records through additive migrations. |
| Memory lifecycle | `waku/memory/`, `waku/tools/notes.py`, `waku/tools/memory_admin.py` | Centralize writes and add evidence, correction, suppression and retrieval policy. |
| Evaluation | `evals/deterministic/`, `evals/judge/`, `evals/helpers.py`, `waku/ops/memory_arena.py`, `waku/ops/release_gate.py` | Add scenario fixtures and comparison reporting within the current framework. |
| Observability | `waku/ops/tracing.py`, existing Ops/Memory frontend | Add attributed usage, real timings and checkpoint/memory events. |

Each version is independently reviewable and has a feature-off or compatibility path where it changes behavior.
Implementation should use the standard library and existing SDKs by default. It should reuse SQLite, the existing loop, tools and evaluation harness.
The proposal does not require a new dashboard application, a separate learning module, a new agent framework, a distributed queue, a vector service or a multi-agent rewrite.

The dependency sequence is V0 -> V1 -> V2 -> V3 -> V4 -> V5.
Evaluation begins in V0 and accompanies every version. V2 is the first milestone to use and evaluate before investing in the remaining memory work.
The reviewed design, isolated baseline and failure tests are the first implementation deliverables.
