# V2: persistent conversation checkpoints

V2 keeps older task details in a session checkpoint and restores recent complete
message groups from SQLite. It adds the opt-in `compact` context policy and
keeps V1's `budget` policy as the default. Real-model summary quality remains
unmeasured.

## Implemented behavior

The checkpoint records goals, constraints, completed work, decisions, unresolved
work and next steps. Every summary entry cites source message IDs. Each revision
records its coverage boundary, first retained message, source hash, prompt hash,
model calls and available usage. SQLite publishes the summary and boundary in
one transaction. A changed revision or changed source hash rejects publication.
Malformed, empty, oversized or incomplete summaries keep the previous checkpoint.

Automatic compaction runs when prior history exceeds the configured turn limit
or the assembled request exceeds its budget. It keeps four recent turns by
default; budget pressure may compact all prior complete turns. The active turn
and its tool-call/result sequence stay intact. `/compact` uses the same service
through the terminal, dashboard and Telegram. It adds no chat turn and executes
no tools.

Summarization uses the main model unless a separate same-provider model is
configured. Source text is split into bounded segments and batches, with a
maximum of 32 summary calls per attempt. Summary requests reserve their output
allowance and pass the shared budget guard. Large saved tool results use V1's
bounded previews and result IDs; their full content remains on disk. The summary
does not claim to have read omitted output. Six summary fields together must
fit within 4,096 UTF-8 bytes.

Restart and session switching load the current checkpoint and remaining raw
message groups. Current rules are rebuilt independently of summary text. The
execution ledger supplies stable result references independently of model prose.
Provider context errors permit one smaller request retry. They cannot restart
the tool sequence or trigger the OpenAI token-parameter fallback.

## Frozen B/B2 comparison

Both policies ran revision `444e542` against the same 36 V0 scenarios, covering
1,632 turns and 84 tool executions each. Disposable homes isolated both runs.
All execution, pairing, source-record, result-recovery and session-isolation
checks passed. The fixture hash remains
`bab4c5fd9911bf3692681a1bd4725cade9c14018059a53910dd5427d03ceea1f`.

| Metric | B: V1 budget | B2: V2 compact |
|---|---:|---:|
| Completed execution scenarios | 36/36 | 36/36 |
| Scripted model calls | 3,600 | 3,754 |
| Summary calls and published checkpoints | 0 | 154 |
| Estimated total input across all stages | 19,006,470 | 20,121,937 |
| Estimated largest request input | 12,883 | 13,796 |
| Budget violations | 0 | 0 |
| Requests rejected before dispatch | 0 | 0 |
| Constraint cases retaining final input evidence | 3/6 | 6/6 |
| Tool receipt cases retaining final input evidence | 3/6 | 6/6 |
| Session recovery cases retaining final input evidence | 3/6 | 6/6 |
| Local scripted median turn duration | 13.53 ms | 22.16 ms |
| Local scripted p95 turn duration | 26.20 ms | 37.88 ms |
| Real tokens, cost and model quality | Unmeasured | Unmeasured |

B2 spends 154 additional scripted calls and 5.9% more estimated input to keep
older evidence available. These results measure an explicit retention tradeoff;
they do not demonstrate lower cost. The estimator uses serialized UTF-8 bytes,
not provider tokenization. The two runs shared one Windows host concurrently,
so the recorded durations are diagnostic, not controlled latency benchmarks.

The scripted summarizer reads only the supplied source segments and previous
summary. It cannot access future fixture answers. Final answer text remains
scripted, so successful execution and input evidence do not prove that a real
model will use that evidence correctly. Source-ID validation verifies references,
not the truth of summary prose.

Correction and forgetting probes expose the next required change. B retains
obsolete content in 3/6 correction and 3/6 forgetting cases; B2 retains it in
6/6 for both. The latest facts are still available, but old transcripts and
summaries can reintroduce stale content. V3 must coordinate corrections and
forgetting across these surfaces before a combined memory release.

## Reproduction and verification

```powershell
.venv/Scripts/python.exe -m evals.context.runner --configuration B --split all --output eval-results/context-v2-B.json
.venv/Scripts/python.exe -m evals.context.runner --configuration B2 --split all --output eval-results/context-v2-B2.json
.venv/Scripts/python.exe -m waku.ops.release_gate --strict --output eval-results/gate-v2
```

The runners install offline isolation before constructing Waku. They use
synthetic models, disposable homes and no real credentials. Full local reports
include prompt templates, per-call hashes and stage timing, source manifests,
outcome checks and compaction events. `eval-results/` stays outside Git.
The strict gate intentionally omits `--live`; its quality verdict remains
incomplete because no paid judge run was requested.

The final gate passed **1,065 offline checks**, skipped **63**, and failed **0**
on Windows/Python 3.13. The skipped cases require live APIs, optional extras or
macOS. An earlier run recorded a multi-minute host pause inside an existing
150 ms concurrency test. That unchanged module passed on its own, and the
subsequent complete run passed in 128.85 seconds.

Ruff, six bundled skill checks and the generated environment template check
passed. Deterministic regressions cover repeated compaction, invalid summaries,
concurrent publication, source mutation, restart, session switching, current
rules, smaller model capacity, oversized source chunks, call limits, zero
history, unknown executions, streaming signatures and recovery without tool
replay.

## Operating limits

- `WAKU_CONTEXT_POLICY=compact` enables V2. The [command reference](commands.md)
  describes summary-model, capacity, output, retained-turn and call settings.
  The same provider credentials serve normal chat and compaction.
- Text-only legacy sessions import their original chat-log row references.
  Mixed legacy and structured histories require a new compact session or the
  V1 budget policy. V2 does not guess a mapping that could lose old exchanges.
- Interrupted turns and unknown action outcomes stop with a reconciliation
  message. Waku cannot infer an external action's success after a crash.
- Very large active turns, oversized persistent instructions or a growing
  execution ledger can still exhaust the request budget. V2 reports a size
  error instead of discarding required records or replaying tools.
- Compaction adds disk records and model calls. Missing usage stays null in
  the ledger and reports; the existing spend view totals measured usage only.
- Long-term consolidation batching and consistent correction/forgetting remain
  V3 work. V2 does not delete original transcripts or claim reliable suppression.
