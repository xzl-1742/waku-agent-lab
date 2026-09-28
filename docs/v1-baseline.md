# V1: bounded requests and recoverable tool results

V1 adds a context budget to Waku and preserves full tool results outside the
model prompt. It keeps the original window policy selectable for comparison.
It does not summarize older conversation or change the memory lifecycle.

## Implemented behavior

Every request through Waku's shared client checks the system prompt, memory,
skills, tool schemas, history and pending messages. The budget reserves the
request's output allowance plus a safety margin. Main-loop requests drop complete
old exchanges when needed; the current request and tool-call/result pairs remain
intact. A required request that cannot fit stops with an explicit error.

The default estimator counts UTF-8 JSON bytes plus framing overhead. Counts are
estimates, not exact provider tokens. Positive observed input usage can increase
future calibration for that model, including cache input counts. Missing usage
and synthetic zeroes cannot reduce estimates. Edits and reductions always trigger
a fresh estimate; observations retain the corresponding request hash.

Main and small-model capacities can be configured separately. A model without
an applicable override uses a conservative 32,768-token local policy. This fallback
does not claim that the provider supports that context length. When both roles
use the same model ID, the smaller configured capacity applies.

Large tool outputs become bounded observations with an execution state, quoted
outcome fields, head/tail excerpts and a result ID. Full UTF-8 output is retained
under `results/<id>.txt`. `manage_memory read_result` reads bounded pages of that
result within the active session, using byte offsets and `next_offset` for Unicode.
It cannot read arbitrary paths or another session's artifacts. Small outputs remain
unchanged. Free-form tool claims remain unverified claims of external success.

The additive `session_messages` table retains original structured messages, with
turn and call IDs. `tool_executions` records pending calls before execution and
completed calls after the full result is written. An interrupted pending record
means the outcome is unknown. Budget, recording and graph failures after execution
cannot automatically replay the action. Existing chat rows remain compatible.

## Frozen A/B experiment on 2026-09-28

Both experiments used code revision `e7c63ec`, the 36 frozen V0 scenarios and
separate disposable homes. Each policy completed 1,632 user turns and 84 tool
executions. All scenario state checks passed. B additionally passed all 36
canonical-record and artifact-recovery checks, with valid call/result pairing.

| Metric | A: original window | B: context budget |
|---|---:|---:|
| Completed execution scenarios | 36/36 | 36/36 |
| Scripted model calls | 3,600 | 3,600 |
| Estimated total input, all model stages | 28,835,662 | 19,006,470 |
| Estimated largest request input | 75,484 | 12,883 |
| Requests exceeding the configured comparison budget | 281 | 0 |
| Requests rejected before model dispatch | 0 | 0 |
| Local scripted median turn duration | 25.45 ms | 47.79 ms |
| Local scripted p95 turn duration | 39.05 ms | 77.11 ms |
| Real input/output tokens and cost | Unmeasured | Unmeasured |
| Real-model task quality | Incomplete | Incomplete |

B reduced estimated total input by **34.1%** and peak input by **82.9%**, with
no extra model calls. The estimator deliberately overcounts relative to many
tokenizers, so these percentages are not measured token savings or cost savings.
The 281 A violations describe estimates against B's policy, not actual API errors.

The experiment used 32,768 capacity, 8,192 main-output reserve, 1,024 safety margin
and 4,096-byte tool observations. All gate/answer/consolidation requests contribute
to totals. B's read-result instruction and tool-schema additions are included.
A retains the old prompt surface. Shared correctness fixes and additive schema
apply to both. The fixture SHA-256 remains
`bab4c5fd9911bf3692681a1bd4725cade9c14018059a53910dd5427d03ceea1f`.

These runs executed concurrently with each other and the release gate on one
Windows host. B's recorded local latency is higher and includes durable result
writes. Those timings are diagnostic observations, not a controlled latency
benchmark or an estimate of API latency. A serial repeated live experiment is
needed before making a performance promotion claim.

Input-evidence probes remain unchanged from V0: each policy retains the current
constraint in 3/6 constraint cases and the old value in 3/6 correction and 3/6
forgetting cases. V1 bounds input size; it does not solve long-term retention or
forgetting consistency. V2 checkpoints and V3 memory lifecycle work remain needed.

## Reproduction

The final strict gate passed **994 offline checks**, skipped **63** and failed
**0** on Windows/Python 3.13. The skips cover live APIs, optional extras and macOS
capabilities. Ruff, all six bundled skill validations, the generated environment
template check and rulebook checks passed. The gate correctly kept real-model
quality incomplete. No paid API calls were made for this verification.

```powershell
.venv/Scripts/python.exe -m evals.context.runner --configuration A --split all --output eval-results/context-v1-A.json
.venv/Scripts/python.exe -m evals.context.runner --configuration B --split all --output eval-results/context-v1-B.json
.venv/Scripts/python.exe -m waku.ops.release_gate --strict --output eval-results/gate-v1
```

The commands use scripted models and do not load real credentials. The strict
gate intentionally omits `--live`; required real-model coverage remains incomplete.
Full local artifacts contain request estimates/hashes, source manifests, prompt
templates, tool-schema hashes, stage timings and outcome checks. `eval-results/`
is ignored by Git. Configuration C/D and paid scenario comparisons are unavailable.

## Operational limits

- Full results and canonical records consume additional disk space. No automatic
  deletion or retention policy is introduced.
- Original transcripts can contain corrected or forgotten facts. V1 does not
  promise suppression across those records or model input.
- The existing consolidator leaves an oversized backlog unprocessed. Bounded
  consolidation batches belong to V3; rejected helper requests are observable.
- Runtime tool execution state records what Waku observed. It does not guarantee
  exactly-once execution of arbitrary external actions after a crash.
- Direct custom SDK calls outside the guarded Waku client are outside this policy.
  Standalone loops and graph LLM nodes still enforce a conservative request budget;
  durable records and result reading require the Waku runtime's injected store.

The [evaluation guide](evals.md#context-budgets-and-ab-comparisons-v1-and-v2) lists the
configuration variables and their defaults. `WAKU_CONTEXT_POLICY=window` restores
the baseline prompt policy without deleting existing records or artifacts.
