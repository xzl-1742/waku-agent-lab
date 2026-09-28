# Status

**What is true right now.** Rewritten whole when it changes, never appended to
— a status file that grows is a changelog, and git already is one.

Read this before opening a PR or filing an issue: most of what is already
known-broken is below, and half of it already has a fix in flight.

**Last updated:** 2026-09-28

---

## What works

The four pillars run: the loop, memory (semantic + episodic + procedural with
a retrieval gate), tools, and both eval tiers. `waku`, `waku dashboard`,
`waku voice`, `waku telegram`, `waku discord`, `waku brief` and
`waku connect google` all start.

**1065 checks pass in the isolated offline suite**, with no API key; 63 checks
skip because they require API access, optional extras or macOS. CI runs the offline tier on every PR along with
ruff, the skills validator, and a check that `.env.example` still matches the
integrations registry.

**V0 context/memory baseline is available.** Thirty-six synthetic scenarios cover
1,632 turns with call timings, state checks and reproducibility metadata. Real
model quality and cost remain unmeasured. See [the V0 report](v0-baseline.md).

**V1 bounds requests and tool observations by default.** The frozen A/B run
completed all 36 scenarios on each policy. Estimated total input fell 34.1%,
peak input fell 82.9%, and no B request exceeded its configured estimate budget.
Durable message/tool records and session-scoped result reads preserve original
outputs. Local scripted latency increased; real token cost and model quality are
unmeasured. See [the V1 report](v1-baseline.md).

**V2 adds opt-in session compaction.** `WAKU_CONTEXT_POLICY=compact` stores
canonical message groups, complete tool receipts and revisioned task
checkpoints. The compactor keeps recent turns, cites source message IDs in six
summary fields, reloads current rules after restart, and makes one bounded
recovery attempt after a provider context rejection. `/compact` works through
the existing CLI, dashboard and Telegram command paths. The deterministic B2
scenarios exercise source retention and request limits; real-model retention
quality and cost remain unmeasured. `budget` remains the default while V2 is
being evaluated. See [the V2 report](v2-baseline.md).

**0.1.8 is on PyPI and on GitHub Releases.** Pushing a `v*` tag publishes to
both, so the repo's "Latest" release always matches `pip install waku-agent`.

**The dashboard uses the Waku Memory design system**, and
`test_design_system.py` keeps it from drifting. See
[context/design-system.md](context/design-system.md).

## Known broken

Nothing here is a surprise. If you hit one of these, the issue exists.

| What | Where | Fix in flight |
|---|---|---|
| The model picker offers OpenAI models that 404 on use | #137 | #178 |
| GPT-5.6 tool calls fail on Chat Completions | — | #146 |
| OpenCode Zen fails with a rate-limit error | #112 | #113 |
| Google Calendar sign-in has no bundled OAuth client, so `waku connect google` needs your own `.waku/credentials.json` | — | — |

**Providers are the recurring theme.** Three of the items above are one
provider or another, and there is no single place that says which providers
are known-good today. Until there is, treat the model picker as a list of
things that *might* work.

## What is deliberately not built

Not a framework, not multi-agent, not production — see
[architecture.md](architecture.md).

Additionally, and worth stating because people ask:

- **No Windows CI.** V0 has a local Windows/Python 3.13 offline verification;
  hosted services, native macOS tools and live model quality remain unverified there.
- **The judge evals are not in CI.** `make gate` explicitly enables paid judge
  evaluation and requires complete live coverage. Missing credentials or skipped
  live checks leave quality incomplete. CI runs isolated offline checks.
- **No provider smoke check.** Nothing verifies that a model in the picker
  resolves, which is why #137 reached a user.

## Open questions

1. **Where the memory pillar ends and Waku Memory begins.** This repo's memory
   is local, single-machine, and yours. Waku Memory is the same memory across
   several agents, and it is a paid hosted service. Both are true and the
   README does not yet say either plainly, so a reader has to work out the
   difference alone.

## Not in the repo

Deliberately absent, so nobody goes looking:

- Filming and demo notes — production material, not product documentation
- Session handoffs — this file replaces them
- Plans and specs — they belong with the work, not in `docs/`
