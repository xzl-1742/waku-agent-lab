# V0: context and memory baseline

V0 restores a measurable baseline and provides the fixtures and reports for later
context and memory changes. The implementation uses the original 12-exchange
history policy, with the zero-window bug fixed. It does not implement compaction.

## Verification on 2026-09-27

The isolated Windows/Python 3.13 run passed **924 checks**, skipped **63** and
failed **0**. Before restoring the missing `Session.build_system()` in the working
copy, the same existing suite passed 847 checks and failed 17; all 17 failures
pointed to that missing method. V0 adds 64 checks in total, including four isolation
checks that were already present when the pre-restoration baseline was measured.

The 63 skips cover 48 hosted-store cases, 12 model/API cases, two macOS cases
and the missing optional MCP transport extra. They are missing coverage,
not successful checks. Ruff, all six bundled skill validations, the generated
`.env.example` check and the rulebook checks pass.

```powershell
.venv/Scripts/python.exe -m evals.offline -q -rs evals/deterministic
.venv/Scripts/ruff.exe check waku evals scripts
.venv/Scripts/python.exe -m evals.context.runner --split all --output eval-results/context-v0.json
.venv/Scripts/python.exe -m waku.ops.release_gate --strict --output eval-results/gate-v0
```

The strict gate command intentionally omits `--live`. The end-to-end run reports
quality as `incomplete` after 924 offline checks pass; the gate's tested return code
is 2 for incomplete coverage. No paid model evaluation
was performed. `--live` explicitly permits credential loading and paid judge calls.

## Synthetic experiment A

The frozen fixture bank contains 24 development and 12 reserved scenarios.
Each of six families has four development cases and two reserved cases. The
normalized fixture SHA-256 is
`bab4c5fd9911bf3692681a1bd4725cade9c14018059a53910dd5427d03ceea1f`.
Reserved cases were exercised to validate the runner; no model or policy was tuned.

All 36 scenarios completed their execution checks across **1,632 user turns**.
The production loop made **3,600 scripted client calls**: 1,632 retrieval gates,
1,704 answers/tool decisions and 264 consolidations. The 84 tool executions
include 36 log reads, 18 note saves, 24 memory searches/updates/deletions and six
local action receipts. Restart cases reopen the same disposable database.

| Family | Completed scenarios | Model input contains current expected evidence at the final turn | Model input still contains an obsolete value |
|---|---:|---:|---:|
| Task constraints | 6/6 | 3/6 | Not applicable |
| Tool outcomes | 6/6 | 3/6 | Not applicable |
| Corrections | 6/6 | 6/6 | 3/6 |
| Forgetting and unknown answers | 6/6 | Not applicable | 3/6 |
| Chinese and pronoun retrieval | 6/6 | 6/6 | Not applicable |
| Session and project isolation | 6/6 | 3/6 | Not applicable |

The database checks pass because scripted tool decisions produce the expected
stored facts and action counts. The evidence probes also expose baseline gaps:
older constraints and receipts can leave the prompt, and a deleted or corrected
fact can remain in recent chat history. Those observations motivate V1/V2 and V3.
They do not measure whether a real model answers correctly.

The script supplies the correct retrieval query, answer and tool choice. It also
supplies empty consolidation results. Consequently, retrieval-gate quality,
memory extraction quality, semantic correctness and real token cost remain
unmeasured. `task_success`, token totals and cost are `null`; quality is
`incomplete`. Configurations B/C/D remain unavailable.

## Reproducing and interpreting the artifact

`eval-results/context-v0.json` records the source commit plus an allowlisted file
hash manifest, configuration, Python/platform, fixed prompt clock, model labels,
prompt templates, fixture hashes and reference notes. The manifest describes the
actual source snapshot, including uncommitted code if a run has any. Reports are
ignored by Git; each developer can regenerate the full call-level artifact.
The final local artifact was generated against code revision `e93f7e1`.

Each scenario records state checks, exceptions, tool calls, per-call durations,
per-turn durations and input evidence probes. Monotonic timings surround client
and tool execution. The report includes median and p95 turn durations, but those
are local scripted timings and must not be presented as real-model latency.
Client-call counts do not include hidden SDK retries. Synthetic usage stays null
even though the existing fake client supplies zero-valued token counters.

The offline bootstrap clears application credentials and settings before Waku
imports, redirects the home and propagates guards into Python children. It blocks
external DNS, TCP and UDP while permitting loopback fixtures. Tests of dotenv
discovery use only synthetic files in the scratch directory. Native executables
remain outside this Python guard and must be mocked in offline tests.

The reference notes pin Pi to
`ff72faba28d10c86611863d0aaa5d3122f2d8cb0` and record official Claude Code
documentation accessed on 2026-09-25. They contain paraphrases rather than a
vendored upstream implementation. See `evals/context/references.json`.

## Next milestone

V1 adds an input budget and bounded tool output. It uses this A baseline and the
frozen scenarios to compare input size and constraint availability. V2 adds
persisted summaries and resume checkpoints; V3 adds correction and forgetting
consistency. Model-quality promotion waits for separately budgeted live runs.
