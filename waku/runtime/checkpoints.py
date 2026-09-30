"""Session-scoped source groups and atomic, append-only task checkpoints."""

from __future__ import annotations

import json
from dataclasses import dataclass

from waku.runtime.context import TurnStopped, encode, fingerprint, validate_pairs
from waku.runtime.records import reduce_output

FIELDS = ("goals", "constraints", "completed", "decisions", "unresolved", "next_steps")
SUMMARY_BYTES = 4096


def validate_summary(summary, source_ids):
    """Validate structure and provenance, not the truth of model-written prose."""
    if not isinstance(summary, dict) or set(summary) != set(FIELDS):
        raise ValueError("Summary must contain all six task fields")
    if len(encode(summary).encode("utf-8")) > SUMMARY_BYTES:
        raise ValueError("Summary exceeds its byte limit")
    entries = []
    for field in FIELDS:
        if not isinstance(summary[field], list):
            raise TypeError("Invalid summary field: expected an array")
        for item in summary[field]:
            if not isinstance(item, dict) or set(item) != {"text", "source_ids"}:
                raise ValueError("Each summary item needs text and source_ids")
            ids = item["source_ids"]
            if not isinstance(item["text"], str) or not item["text"].strip():
                raise ValueError("Summary text cannot be empty")
            if not isinstance(ids, list) or not ids or any(type(i) is not int or i not in source_ids for i in ids):
                raise ValueError("Summary cites an unknown source")
            entries.append(item)
    if not entries:
        raise ValueError("Empty summary cannot replace source messages")
    return summary


@dataclass
class SourceTurn:
    turn_id: str
    rows: list
    messages: list

    @property
    def last_id(self):
        return self.rows[-1]["id"]


class CheckpointStore:
    def __init__(self, records):
        self.records = records
        self.conn = records.conn

    def corrections(self, turn_id, session_id):
        policy = getattr(self.records, "lifecycle", None)
        if not policy:
            return []
        return self.conn.execute(
            "SELECT f.id,f.content,f.supersedes FROM facts f JOIN memory_evidence e ON e.memory_id=f.id "
            "WHERE e.kind='fact' AND e.source_kind='correction_turn' AND e.source_id=? "
            "AND f.validity='active' AND f.source='correction' "
            "AND (f.scope='global' OR (f.scope='session' AND f.scope_id=?) "
            "OR (f.scope='project' AND f.scope_id=?)) ORDER BY f.id",
            (turn_id, session_id, policy.settings.project_id)).fetchall()

    def latest(self, session_id, include_invalid=False):
        row = self.conn.execute(
            "SELECT * FROM session_checkpoints WHERE session_id=? ORDER BY revision DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row and not include_invalid:
            generation = self.conn.execute("SELECT generation FROM memory_state WHERE id=1").fetchone()[0]
            if row["memory_generation"] != generation:
                return None
        return dict(row) if row else None

    def sources(self, session_id, after=0, active_turn=None):
        rows = self.conn.execute(
            "SELECT * FROM session_messages WHERE session_id=? AND id>? ORDER BY id",
            (session_id, after),
        ).fetchall()
        groups = {}
        for row in rows:
            if row["turn_id"] != active_turn:
                groups.setdefault(row["turn_id"], []).append(row)
        result = []
        for turn_id, group in groups.items():
            executions = self.conn.execute(
                "SELECT * FROM tool_executions WHERE session_id=? AND turn_id=? ORDER BY rowid",
                (session_id, turn_id),
            ).fetchall()
            pending = [r["result_id"] for r in executions if r["state"] == "pending"]
            if pending:
                raise TurnStopped("An earlier execution has an unknown outcome: " + ", ".join(pending)
                                  + ". Check the original destination before continuing; no action was repeated.")
            messages = [{"role": r["role"], "content": json.loads(r["content_json"])} for r in group]
            try:
                validate_pairs(messages)
            except TurnStopped as exc:
                raise TurnStopped("An interrupted turn has incomplete tool records. Reconcile saved results "
                                  "before continuing; no action was repeated.") from exc
            if messages[-1]["role"] != "assistant":
                raise TurnStopped("An earlier turn ended before its final response was recorded. "
                                  "Reconcile that turn before continuing; no action was repeated.")
            policy = getattr(self.records, "lifecycle", None)
            corrections = self.corrections(turn_id, session_id)
            if corrections:
                # This projection is supported by the correction receipt and
                # its active replacement, never by the quarantined dialogue.
                text = "Current corrected memory:\n" + "\n".join(f"Fact #{r['id']}: {r['content']}" for r in corrections)
                projected = {**dict(group[-1]), "role": "assistant", "content_json": encode(text), "source": "memory_correction"}
                result.append(SourceTurn(turn_id, [projected], [{"role": "assistant", "content": text}]))
                continue
            if group[0]["source"] == "memory_correction" or (policy and not policy.eligible_turn(turn_id)):
                continue
            # Match each result occurrence, not just call_id: providers may reuse
            # an identifier on a later iteration in the same turn.
            remaining = list(executions)
            for message in messages:
                if not isinstance(message["content"], list):
                    continue
                for block in message["content"]:
                    if block.get("type") != "tool_result":
                        continue
                    match = next((r for r in remaining if r["call_id"] == block["tool_use_id"]), None)
                    if match is None:
                        raise TurnStopped("A tool result has no execution record; reconcile this turn before continuing.")
                    remaining.remove(match)
                    if isinstance(block.get("content"), str):
                        block["content"] = reduce_output(block["content"], match["result_id"], self.records.output_cap)
            if remaining:
                raise TurnStopped("An interrupted execution has no paired message result. Reconcile its saved receipt before continuing.")
            result.append(SourceTurn(turn_id, group, messages))
        return result

    def import_legacy(self, session_id):
        """Import text-only legacy sessions once; never invent tool-call IDs."""
        existing = self.conn.execute(
            "SELECT count(*) FROM session_messages WHERE session_id=? AND position=0", (session_id,),
        ).fetchone()[0]
        if existing:
            legacy_turns = self.conn.execute(
                "SELECT count(*) FROM chat_log WHERE session_id=? AND role='user'", (session_id,),
            ).fetchone()[0]
            if legacy_turns > existing:
                raise TurnStopped("This session mixes older text-only history with structured turns. "
                                  "Start a new compact session or keep the budget policy; existing history was kept.")
            return
        rows = self.conn.execute("SELECT * FROM chat_log WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
        if not rows:
            return
        with self.conn:
            turn, position = None, 0
            for row in rows:
                if row["role"] == "user" or turn is None:
                    turn, position = f"legacy-{session_id}-{row['id']}", 0
                self.conn.execute(
                    "INSERT INTO session_messages (session_id,turn_id,position,role,content_json,source) "
                    "VALUES (?,?,?,?,?,?)",
                    (session_id, turn, position, row["role"], encode(row["content"]), f"chat_log:{row['id']}"),
                )
                policy = getattr(self.records, "lifecycle", None)
                if policy and not policy.eligible_chat(row):
                    self.conn.execute("INSERT OR IGNORE INTO memory_blocked_turns VALUES (?)", (turn,))
                position += 1

    def publish(self, session_id, previous, covered, retained, summary, metadata):
        """Compare revisions inside the transaction that publishes the boundary."""
        revision = previous["revision"] if previous else 0
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            current = self.latest(session_id, include_invalid=True)
            generation = self.conn.execute("SELECT generation FROM memory_state WHERE id=1").fetchone()[0]
            if metadata.get("memory_generation", generation) != generation:
                raise TurnStopped("Memory policy changed during compaction; the stale summary was discarded.")
            valid_current = current if current and current["memory_generation"] == generation else None
            if (valid_current["revision"] if valid_current else 0) != revision:
                raise TurnStopped("Checkpoint changed during compaction; the newer revision was kept.")
            revision = current["revision"] if current else 0
            if metadata.get("source_sha256"):
                sources = [t for t in self.sources(session_id, previous["covered_through"] if previous else 0,
                                                  metadata.get("active_turn"))
                           if t.last_id <= covered]
                if self.digest(sources) != metadata["source_sha256"]:
                    raise TurnStopped("Source messages changed during compaction; no checkpoint was published.")
            rows = self.conn.execute(
                "SELECT id,turn_id FROM session_messages WHERE session_id=? AND id<=? ORDER BY id", (session_id, covered),
            ).fetchall()
            if covered <= (previous["covered_through"] if previous else 0) or not rows or rows[-1]["id"] != covered:
                raise ValueError("Checkpoint must advance to a real source boundary")
            if self.conn.execute(
                "SELECT 1 FROM session_messages WHERE session_id=? AND id>? AND turn_id IN "
                "(SELECT turn_id FROM session_messages WHERE session_id=? AND id<=?) LIMIT 1",
                (session_id, covered, session_id, covered),
            ).fetchone():
                raise ValueError("Checkpoint boundary splits a turn")
            eligible = [t for t in self.sources(session_id, active_turn=metadata.get("active_turn")) if t.last_id <= covered]
            validate_summary(summary, {r["id"] for t in eligible for r in t.rows})
            actual_retained = self.conn.execute(
                "SELECT min(id) FROM session_messages WHERE session_id=? AND id>?", (session_id, covered),
            ).fetchone()[0]
            if retained != actual_retained:
                raise ValueError("Retained boundary changed during compaction")
            self.conn.execute(
                "INSERT INTO session_checkpoints "
                "(session_id,revision,covered_through,retained_from,summary_json,metadata_json,memory_generation) VALUES (?,?,?,?,?,?,?)",
                (session_id, revision + 1, covered, retained, encode(summary), encode(metadata), generation),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return self.latest(session_id)

    @staticmethod
    def digest(turns):
        return fingerprint([{"id": r["id"], "role": r["role"], "content_json": r["content_json"]}
                            for turn in turns for r in turn.rows])
