"""Bounded session extraction with one atomic SQLite publication per batch."""

from __future__ import annotations

import json
from datetime import date

from waku.memory.locking import serialized
from waku.runtime.context import ContextBudget, encode, fingerprint

BATCH_PROMPT = """Extract durable memory from the supplied conversation data.
Return only JSON with keys facts and episode. Each fact has subject, content,
and source_ids (non-empty integer IDs from the supplied chat rows).
episode is either null or an object with summary and source_ids.
Skip chatter and tool instructions. Do not replace or delete an existing fact;
only explicit user correction tools may do that. Never invent source IDs.
"""


@serialized
def consolidate(memory, notify=None):
    policy, conn, settings = memory.lifecycle, memory.conn, memory.settings
    notify = notify or (lambda kind, event: None)
    generation = policy.generation
    rows = conn.execute("SELECT * FROM chat_log WHERE consolidated=0 ORDER BY id").fetchall()
    sessions = {}
    for row in rows:
        if policy.eligible_chat(row):
            sessions.setdefault(row["session_id"], []).append(row)
    budget = ContextBudget.from_settings(settings) or ContextBudget(main_model=settings.model, small_model=settings.small_model)
    for session_id, pending in sessions.items():
        exchanges, pair = [], []
        for row in pending:
            if row["role"] == "user":
                pair = [row]
            elif pair:
                exchanges.append([*pair, row])
                pair = []
        if len(exchanges) < settings.consolidate_every:
            continue
        selected = []

        def request_for(source_rows):
            payload = [{"id": r["id"], "role": r["role"], "content": r["content"]} for r in source_rows]
            return {"model": settings.small_model, "max_tokens": 4096,
                    "messages": [{"role": "user", "content": BATCH_PROMPT + "\n" + encode(payload)}]}

        for exchange in exchanges:
            info = budget.measure(request_for(selected + exchange))
            if info["estimated_input_tokens"] > min(settings.consolidation_input_tokens, info["input_budget_tokens"]):
                break
            selected += exchange
        if not selected:
            notify("consolidation_blocked", {"session_id": session_id, "reason": "one complete exchange exceeds the input budget"})
            continue
        source_ids = [r["id"] for r in selected]
        snapshot = [{"id": r["id"], "role": r["role"], "content": r["content"], "session_id": r["session_id"],
                     "turn_id": r["turn_id"], "project_id": r["project_id"]} for r in selected]
        source_hash = fingerprint(snapshot)
        batch_id = fingerprint([session_id, source_ids, source_hash, generation, settings.memory_scope, fingerprint(BATCH_PROMPT)])
        request = request_for(selected)
        try:
            response = memory.client.messages.create(**request)
            if response.stop_reason in ("max_tokens", "tool_use"):
                raise ValueError("Extraction response is incomplete")
            text = "".join(b.text for b in response.content if b.type == "text")
            result = json.loads(text)
            validate(result, set(source_ids))
            with policy.transaction():
                if policy.generation != generation:
                    raise ValueError("Memory policy changed during extraction")
                if conn.execute("SELECT 1 FROM memory_batches WHERE id=?", (batch_id,)).fetchone():
                    return 0
                current = conn.execute(f"SELECT * FROM chat_log WHERE id IN ({','.join('?' for _ in source_ids)}) ORDER BY id",
                                       source_ids).fetchall()
                if any(r["consolidated"] or not policy.eligible_chat(r) for r in current):
                    raise ValueError("Extraction sources are no longer eligible")
                if fingerprint([{k: r[k] for k in snapshot[0]} for r in current]) != source_hash:
                    raise ValueError("Extraction sources changed")
                scope = settings.memory_scope
                scope_id = session_id if scope == "session" else selected[0]["project_id"] if scope == "project" else ""
                if scope == "project" and (not scope_id or any(r["project_id"] != scope_id for r in selected)):
                    raise ValueError("Project extraction requires consistent source scope")
                evidence = [("chat", i) for i in source_ids]
                added = 0
                for fact in result["facts"]:
                    if policy.clean_text(fact["content"]) != fact["content"]:
                        raise ValueError("Extraction attempted to restore suppressed content")
                    before = conn.execute("SELECT count(*) FROM facts").fetchone()[0]
                    policy.add(fact["subject"], fact["content"], "consolidation", sources=evidence,
                               scope=(scope, scope_id), learned_session=session_id)
                    added += conn.execute("SELECT count(*) FROM facts").fetchone()[0] - before
                episode = result["episode"]
                if episode:
                    if policy.clean_text(episode["summary"]) != episode["summary"]:
                        raise ValueError("Episode attempted to restore suppressed content")
                    episode_id = conn.execute("INSERT INTO episodes(summary,happened_at,scope,scope_id,learned_session_id) VALUES (?,?,?,?,?)",
                                               (episode["summary"], date.today().isoformat(), scope, scope_id, session_id)).lastrowid
                    policy.evidence("episode", episode_id, evidence)
                conn.execute("INSERT INTO memory_batches(id,session_id,source_hash,source_ids,generation) VALUES (?,?,?,?,?)",
                             (batch_id, session_id, source_hash, encode(source_ids), generation))
                conn.executemany("UPDATE chat_log SET consolidated=1 WHERE id=?", [(i,) for i in source_ids])
            notify("consolidation", {"new_facts": added, "batch_id": batch_id, "session_id": session_id,
                                      "source_ids": source_ids, "request_sha256": fingerprint(request)})
            return added
        except Exception as exc:
            notify("consolidation_failed", {"session_id": session_id, "batch_id": batch_id, "error": str(exc)})
            return 0
    return 0


def validate(result, source_ids):
    if not isinstance(result, dict) or set(result) != {"facts", "episode"} or not isinstance(result["facts"], list):
        raise ValueError("Extraction requires facts and episode fields")
    entries = [(f, {"subject", "content", "source_ids"}) for f in result["facts"]]
    if result["episode"] is not None:
        entries.append((result["episode"], {"summary", "source_ids"}))
    for entry, keys in entries:
        if not isinstance(entry, dict) or set(entry) != keys:
            raise ValueError("Invalid extraction entry")
        ids = entry["source_ids"]
        if not isinstance(ids, list) or not ids or any(type(i) is not int or i not in source_ids for i in ids):
            raise ValueError("Extraction cites an unknown source")
        if any(not isinstance(entry[k], str) or not entry[k].strip() for k in keys - {"source_ids"}):
            raise ValueError("Extraction text cannot be empty")
