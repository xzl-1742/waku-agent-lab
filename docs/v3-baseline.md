# V3: consistent memory writes, corrections and forgetting

V3 adds an opt-in SQLite lifecycle for durable memory. Explicit saves, automatic
extraction, agent tools and dashboard edits use the selected stores. SQLite
records scope, evidence and validity; an explicit correction links the current
value to its predecessor. Remote stores retain ordinary CRUD with opaque IDs.
Requesting lifecycle guarantees with a remote store fails explicitly.

## Enable the lifecycle

Set these values in the existing configuration and restart Waku:

```dotenv
WAKU_MEMORY_POLICY=lifecycle
WAKU_SEMANTIC_STORE=sqlite
WAKU_EPISODIC_STORE=sqlite
WAKU_MEMORY_SCOPE=global
WAKU_CONSOLIDATION_INPUT=16000
# Optional: combine the lifecycle with V2 session checkpoints.
WAKU_CONTEXT_POLICY=compact
```

`WAKU_MEMORY_SCOPE` accepts `global`, `project` or `session`. Project scope needs
a non-empty `WAKU_PROJECT_ID`. Scope controls where a fact is visible; the
separate learned-session field records where it originated. Global facts and
facts matching the current project or session are eligible before search ranking
and result limits. Existing rows migrate to active global records without
changing their IDs or content. The migration only adds tables and columns.

`legacy` remains the default memory policy. Once a home contains suppression
records, the current binary keeps lifecycle enforcement even if the flag is
changed back to `legacy`. Older binaries do not understand these records and
cannot provide the same guarantee.

## What changes

Exact normalized duplicates within one subject and scope share an active record
and accumulate evidence. Similar wording cannot authorize replacement. Explicit
corrections keep a predecessor link, including corrections to an already stored
value. Relabeling an unchanged fact does not invalidate its content.

Automatic extraction selects complete exchanges from one session and caps the
estimated model input at 16,000 tokens by default, with room reserved for output
and context safety. One invocation publishes at most one batch. It validates the
response shape, cited source IDs, source snapshot and memory generation before
publishing facts, an optional episode, evidence, a stable batch receipt and exact
processed-row markers in one transaction. A failed publication rolls everything
back. New arrivals remain pending. Evidence conservatively records the full
selected batch, even when the model cites only part of it.

A single exchange that cannot fit stays pending and emits a
`consolidation_blocked` event. Invalid or failed extraction emits
`consolidation_failed`. This cap bounds model requests; the current local scan
still loads the pending rows and is not a bounded-memory database iterator.

The dashboard preserves integer and string IDs, including numeric-looking
strings and quotes. It reports failed writes and keeps the editor open for a
retry. Its memory lists, edits and readable export use the selected stores.
Gathered digests reject a source snapshot if memory changes before synthesis
or publication.

## Forgetting deliberately trades context for consistency

A correction or deletion increments a persistent memory generation. The first
implementation conservatively excludes all earlier conversation context and
checkpoints in that home, all derived facts and episodes, and exact copies of the
changed value. Unrelated explicit facts remain active. Older data lacks complete
provenance, so the implementation cannot safely keep only unrelated summaries.
Users may need to restate task context after a correction or deletion.

The original database rows, checkpoint revisions, traces and result files remain
in the archive. Normal retrieval, session reload, eligible consolidation sources,
checkpoint reuse and `MEMORY.md` exclude invalid records. Suppressed result files
cannot reenter through partial result reads. New inputs and observations receive
normalized phrase filtering, while complete explicit replacement values remain
eligible. This filter cannot identify every paraphrase arriving again from an
external source; suppression does not erase archives or external services.

A memory mutation ends its current tool batch with a deterministic reply and
cancels remaining calls in that batch. No further answer-model call sees the old
context. Content-free execution receipts survive context invalidation, and an
unknown execution outcome still blocks continuation for reconciliation.
The readable export is replaced atomically before a successful mutation is
reported. A failed export leaves suppression committed and reports the failure;
the next turn attempts repair before dispatching a model request.

Home-scoped thread and process locks serialize turns and mutations. A model call
holds that lock, so another gateway can wait or time out. The lifecycle adds
database work, receipt persistence and filesystem synchronization. It is not a
latency optimization.

## Frozen scenario results

The comparison uses the unchanged V0 fixture hash
`bab4c5fd9911bf3692681a1bd4725cade9c14018059a53910dd5427d03ceea1f`.
Each configuration covers 36 scenarios and 1,632 turns. `V3-window` uses the
window context policy with lifecycle records and bounded tool previews;
`V3-compact` also uses V2 checkpoints and the request budget guard. Both retain
the existing gate and FTS retrieval policy. V4 retrieval and V5 C/D labels remain
outside this comparison.

The final implementation snapshot is `99296aa`. Both reports record the full
commit and hashes of the evaluated source files.

| Metric | V3-window | V3-compact |
|---|---:|---:|
| Completed scenarios | 36/36 | 36/36 |
| Scripted model calls | 3,574 | 3,720 |
| Compaction calls | 0 | 146 |
| Estimated total input | 17,754,740 | 19,653,928 |
| Largest estimated request input | 11,941 | 13,431 |
| Observed budget violations | 0 | 0 |
| Correction cases with the obsolete value in final input | 0/6 | 0/6 |
| Forgetting cases with the obsolete value in final input | 0/6 | 0/6 |
| Correction cases retaining the current value | 6/6 | 6/6 |
| Constraint cases retaining the required evidence | 3/6 | 6/6 |
| Tool receipt cases retaining the required evidence | 3/6 | 6/6 |
| Session recovery cases retaining the required evidence | 3/6 | 6/6 |
| Real tokens, cost and model quality | Unmeasured | Unmeasured |

The earlier [V2 report](v2-baseline.md) found obsolete values in all six
correction and all six forgetting cases with checkpoints. The V3 cases close
that input-availability gap. They do not establish that a real model will answer
correctly, or that unrelated task context survives a memory mutation.

The answer model is scripted. Scenario extraction deliberately returns no facts;
separate deterministic cases exercise non-empty extraction, failures and retries.
The summarizer sees only supplied sources and its prior checkpoint. Estimated
input uses serialized UTF-8 bytes rather than provider tokenization. Window
policy has no general dispatch budget guarantee despite these scenarios fitting.
Local durations are diagnostic and are not a controlled latency comparison.

## Reproduce and inspect

Run the offline suite and both reports from the repository root:

```bash
python -m evals.offline
python -m ruff check waku evals scripts
python scripts/validate_skills.py
python scripts/generate_env_example.py --check
python -m evals.context.runner --configuration V3-window --split all --output eval-results/context-v3-window.json
python -m evals.context.runner --configuration V3-compact --split all --output eval-results/context-v3-compact.json
```

The runners create disposable isolated homes, block external network calls and
avoid loading the user's dotenv file. Reports include source-file hashes, the
commit, prompt hashes, per-stage calls, execution checks and input probes.
Raw reports and the synthetic browser screenshot live under ignored
`eval-results/`; runtime data is never part of the report.

Deterministic cases cover scope, migration, exact deduplication, correction links,
transaction rollback, arrivals during extraction, stale snapshots, source-ID
validation, request caps, restart, disabled flags, checkpoints, saved-result
reads, interrupted executions, exports, remote IDs and dashboard integration.
Headless Edge also verified editing integer/string/quoted IDs, failed-save
feedback, deletion, reload, navigation and the chat dock with zero console
errors, using a synthetic backend and an isolated home.

The final offline run passed 1,111 checks and skipped 63 checks requiring optional
extras, API access or macOS. Ruff, skill validation, the generated environment
example check and rulebook/static-asset checks passed.

The strict release gate keeps its overall quality status incomplete when the
paid judge tier is skipped. Passing deterministic checks is not permission to
report real-model quality or cost as measured.
