# V4: selective memory retrieval and bounded evidence

V4 adds an opt-in SQLite retrieval policy with context hints, strict gate
decisions, Unicode keyword matching and bounded evidence. The main model can
recover from a gate skip through the existing memory tool. The policy preserves
V3 eligibility checks and keeps the legacy retrieval policy as the default.

## Enable selective retrieval

Set these values in the existing configuration and restart Waku:

```dotenv
WAKU_RETRIEVAL_POLICY=selective
WAKU_SEMANTIC_STORE=sqlite
WAKU_EPISODIC_STORE=sqlite
WAKU_RETRIEVAL_TOP_K=4
WAKU_RETRIEVAL_TOKENS=1024
WAKU_RETRIEVAL_GATE_TOKENS=2048
# Recommended: retain correction, forgetting and checkpoint guarantees.
WAKU_MEMORY_POLICY=lifecycle
WAKU_CONTEXT_POLICY=compact
```

The retrieval, memory and context policies remain independent. Selective
retrieval requires local SQLite facts and episodes; a remote-store combination
fails configuration validation. It uses the existing small model and provider
credentials. It adds no model service, key, default dependency or database index.

`WAKU_RETRIEVAL_POLICY=legacy` restores the prior gate and search behavior.
Disabling retrieval changes does not undo V3 suppression or remove archives.

## Follow one request

The gate receives the current message, up to four recent eligible messages and
a valid checkpoint hint when compaction is enabled. The runtime filters these
sources through V3 suppression before applying excerpt limits. A zero history
window excludes both dialogue and checkpoint hints. The complete gate request
must fit its configured estimate and the small model's input allowance.
Older dialogue is dropped before the checkpoint hint. An oversized required
current message stops the turn without dispatching a model call.

The gate accepts exactly four fields: a boolean `retrieve`, a keyword `query`,
a nonempty `reason` and a `mode` of `search` or `recent`. Prose, duplicate fields,
inconsistent modes and truncated replies fail validation. A malformed response
or ordinary API failure triggers one lexical lookup using a bounded excerpt of
the current message. Terminal budget and suppression failures propagate.
Trace events distinguish a deliberate skip, invalid output, API failure,
search failure and recovery search.

The local search normalizes Unicode separately from lifecycle identity hashes.
It matches words, limited English plural/`ing` forms and Han substrings/bigrams.
It removes common question words and rejects insufficient query coverage.
Scope and active validity filter before ranking. Relevance ranks first, followed
by source preference: explicit corrections, explicit saves, then consolidation.
Freshness breaks ties within a store; the combined list uses a stable kind order.
These scores describe an ordering rule, not calibrated confidence.

Search returns at most the configured number of records with IDs and short
passages. The serialized payload must fit `WAKU_RETRIEVAL_TOKENS`, including
metadata. The estimate counts one token per UTF-8 byte, as V1 does; it is not
provider tokenization. An entry that cannot fit is omitted and counted. A lower
limit can therefore reduce delivered recall even when ranking finds the record.

The existing `manage_memory` tool gains selective `read` and `recent` actions.
The model can issue at most two search/recent requests and three detail-page
reads per turn. `read` accepts `kind`, `id`, `offset` and `limit`; its offsets
count characters. Each page rechecks the entire record's scope, validity and
suppression before slicing. Existing `read_result` offsets still count UTF-8
bytes. Empty keyword queries return no matches; explicit `recent` requests
select eligible episodes. Search recovery does not grant another model loop.

## Frozen retrieval results

The separate bank contains 24 scenarios: 16 development and eight reserved.
Each split covers pronouns, Chinese names within sentences, paraphrases, common
words, conflicting facts, scope boundaries, stale records and unknown answers.
The bank was committed in `36cdbb9` before implementation. Its SHA-256 is
`9f2e0487f623856e21af44eed082df3280dd0d3d7212381022c26d0c8f409f2b`.
The final comparison uses implementation and evaluator snapshot `3c33ec8`.
The JSON report records the full commit and individual source hashes.

Both policies use fresh SQLite stores, lifecycle filtering, `k=4`, a 1,024-token
evidence allowance and identical scripted gate decisions. The old policy keeps
its existing episodic result limit. The selective policy applies one combined
limit. This comparison measures each policy as implemented. Each deterministic
scenario runs once per policy. The reserved split was inspected after the
implementation and evaluator were committed; no ranking rules were tuned on its
results. A subsequent regression fix includes assistant text blocks in compact
dialogue hints and excludes tool/reasoning blocks. It leaves fixture scores unchanged.

| Metric | Legacy control | Selective candidate |
|---|---:|---:|
| Development search Recall@k | 63.6% | 81.8% |
| Development delivered Recall@k | 54.5% | 72.7% |
| Development recall after recovery | 63.6% | 81.8% |
| Reserved search/delivered/after-recovery Recall@k | 66.7% | 66.7% |
| All-case search Recall@k | 64.7% | 76.5% |
| All-case delivered Recall@k | 58.8% | 70.6% |
| All-case recall after recovery | 64.7% | 76.5% |
| Cases delivering forbidden evidence | 3/24 | 0/24 |
| Cases exceeding the evidence allowance | 0/24 | 0/24 |
| Scripted gate false negatives | 1 | 1 |
| Recovery attempts | 1 | 1 |
| Mean relevant serialized-byte share | 53.1% | 7.5% |
| Provider tokens, cost and answer quality | Unmeasured | Unmeasured |

Recall averages the 17 scenarios with known relevant records: 11 development
and six reserved. The seven no-answer scenarios receive no recall score;
forbidden-evidence checks cover them instead. All three legacy forbidden cases
come from common-word queries returning unrelated recent episodes. Both policies
recover the deliberately skipped gate case through the memory tool. Gate
decisions and resolved queries are scripted, so these results do not measure
pronoun understanding or the real gate's false-negative rate.

All 24 selective cases satisfy the declared critical checks: forbidden evidence,
the initial evidence budget and specified source ordering. A complete execution
does not imply complete recall. All three paraphrase cases still miss their
relevant records. The reserved stale-record case excludes the old coffee
preference but also misses the current tea preference: the query says
`Sam preference` while the record says `Sam prefers tea`. This is a lexical-form
mismatch, not a query containing the old value. These four misses remain visible
in the report. Reserved average recall
does not improve, so these results do not justify changing the default.

The relevant-byte share falls because IDs, offsets and other metadata dominate
the very short fixture records. This metric includes that overhead and excludes
gate requests and later recovery output. V4 makes no efficiency claim from
these fixtures. Local call/stage durations are diagnostic rather than a latency
benchmark. Stale and unsupported answer-assertion rates remain `null` because
neither an answer model nor a semantic judge runs in this comparison.

## Limits and next comparison

Keyword matching still lacks general semantic similarity and some word forms. The reserved misses
justify a separately frozen hybrid-retrieval experiment. They do not establish
that an embedding model would improve answers enough to cover its cost. That
optional experiment and real-model evaluation remain V5 work; no embedding
service or fake quality result is added to V4.

The current search scans eligible SQLite rows and retains a top-k heap. Returned
material and query terms are bounded, while scan time grows with the store.
Large individual records still require normalization and suppression checks.
The implementation does not claim constant-time search or a bounded database
working set. Existing V3 correction and forgetting tradeoffs remain unchanged.

## Reproduce and inspect

Run the isolated suite and comparison from the repository root:

```bash
python -m evals.offline
python -m ruff check waku evals scripts
python scripts/validate_skills.py
python -m evals.retrieval.runner --split development --output eval-results/retrieval-v4-development.json
python -m evals.retrieval.runner --split reserved --output eval-results/retrieval-v4-reserved.json
python -m evals.retrieval.runner --split all --output eval-results/retrieval-v4.json
```

The comparison installs offline isolation before importing settings, creates
disposable stores and leaves real runtime data and credentials untouched.
The output records ranked IDs, delivered IDs, recovery IDs, schema outcomes,
budget estimates, timings, prompts and source hashes. Deterministic checks also
exercise gate failures, long Chinese records, partial reads after forgetting,
search/page limits and valid checkpoint hints after restart.

The strict release gate remains incomplete until required live judge coverage
runs. Offline success does not grant a measured model-quality or release claim.
The final Windows/Python 3.13 offline run passes 1,165 checks and skips 63 checks
that need API access, optional extras or macOS. Ruff, skill validation and the
generated configuration check pass. No paid judge runs in this verification.
