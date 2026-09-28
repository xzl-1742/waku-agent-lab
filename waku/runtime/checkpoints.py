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
            raise ValueError("Summary fields must be lists")
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
    receipts: list

    @property
    def last_id(self):
        return self.rows[-1]["id"]


class CheckpointStore:
    def __init__(self, records):
        self.records = records
        self.conn = records.conn

    def latest(self, session_id):
        row = self.conn.execute(
            "SELECT * FROM session_checkpoints WHERE session_id=? ORDER BY revision DESC LIMIT 1",
            (session_id,),
        ).fetchone()
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
            receipts = [{"result_id": r["result_id"], "tool": r["tool"], "state": r["state"],
                         "outcome": json.loads(r["outcome_json"])} for r in executions]
            result.append(SourceTurn(turn_id, group, messages, receipts))
        return result

    def import_legacy(self, session_id):
        """Import text-only legacy sessions once; never invent tool-call IDs."""
        if self.conn.execute("SELECT 1 FROM session_messages WHERE session_id=? LIMIT 1", (session_id,)).fetchone():
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
                position += 1

    def publish(self, session_id, previous, covered, retained, summary, metadata):
        """Compare revisions inside the transaction that publishes the boundary."""
        revision = previous["revision"] if previous else 0
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            current = self.latest(session_id)
            if (current["revision"] if current else 0) != revision:
                raise TurnStopped("Checkpoint changed during compaction; the newer revision was kept.")
            rows = self.conn.execute(
                "SELECT id FROM session_messages WHERE session_id=? AND id<=? ORDER BY id", (session_id, covered),
            ).fetchall()
            validate_summary(summary, {r["id"] for r in rows})
            if covered <= (previous["covered_through"] if previous else 0) or not rows or rows[-1]["id"] != covered:
                raise ValueError("Checkpoint must advance to a real source boundary")
            if self.conn.execute(
                "SELECT 1 FROM session_messages WHERE session_id=? AND id>? AND turn_id IN "
                "(SELECT turn_id FROM session_messages WHERE session_id=? AND id<=?) LIMIT 1",
                (session_id, covered, session_id, covered),
            ).fetchone():
                raise ValueError("Checkpoint boundary splits a turn")
            actual_retained = self.conn.execute(
                "SELECT min(id) FROM session_messages WHERE session_id=? AND id>?", (session_id, covered),
            ).fetchone()[0]
            if retained != actual_retained:
                raise ValueError("Retained boundary changed during compaction")
            self.conn.execute(
                "INSERT INTO session_checkpoints "
                "(session_id,revision,covered_through,retained_from,summary_json,metadata_json) VALUES (?,?,?,?,?,?)",
                (session_id, revision + 1, covered, retained, encode(summary), encode(metadata)),
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
