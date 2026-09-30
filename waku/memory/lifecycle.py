"""SQLite memory versions, exact deduplication and durable source eligibility."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from contextlib import contextmanager
from uuid import uuid4

from waku.memory.locking import serialized
from waku.runtime.context import TurnStopped, encode


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def content_hash(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


class Lifecycle:
    def __init__(self, conn, settings):
        self.conn, self.settings = conn, settings
        self.session_id, self.turn_id = "default", None
        self.after_change = lambda: None
        if self.enabled and (settings.semantic_store != "sqlite" or settings.episodic_store != "sqlite"):
            raise ValueError("Memory lifecycle metadata, suppression and atomic batches require SQLite facts and episodes. "
                             "Remote stores support legacy CRUD only.")

    @property
    def generation(self):
        return self.conn.execute("SELECT generation FROM memory_state WHERE id=1").fetchone()[0]

    @property
    def enabled(self):
        # Disabling enhanced writes must never disable existing suppression.
        return self.settings.memory_policy == "lifecycle" or self.generation > 0

    def scope(self):
        scope = self.settings.memory_scope
        return scope, (self.settings.project_id if scope == "project" else self.session_id if scope == "session" else "")

    def visible_sql(self, alias=""):
        p = alias + "." if alias else ""
        clause = (f"{p}validity='active' AND ({p}scope='global' OR ({p}scope='session' AND {p}scope_id=?) "
                  f"OR ({p}scope='project' AND {p}scope_id=?))")
        return clause, (self.session_id, self.settings.project_id)

    @contextmanager
    def transaction(self):
        nested = self.conn.in_transaction
        if not nested:
            self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            if not nested:
                self.conn.commit()
        except Exception:
            if not nested:
                self.conn.rollback()
            raise

    def evidence(self, kind, memory_id, sources=None):
        sources = sources if sources is not None else ([("turn", self.turn_id)] if self.turn_id else [])
        self.conn.executemany("INSERT OR IGNORE INTO memory_evidence VALUES (?,?,?,?)",
                              [(kind, memory_id, source_kind, str(source_id)) for source_kind, source_id in sources])

    @serialized
    def add(self, subject, content, source="user", *, sources=None, scope=None, learned_session=None, supersedes=None):
        subject = subject.strip().lower()
        if not subject or not content.strip():
            raise ValueError("A memory needs a non-empty subject and content")
        if self.clean_text(content, supersedes=supersedes) != content:
            raise ValueError("This content was suppressed; it cannot be learned again automatically")
        scope, scope_id = scope or self.scope()
        if self.conn.execute("SELECT 1 FROM memory_suppressions WHERE kind='fact' AND content_hash=? "
                             "AND scope=? AND scope_id=?", (content_hash(content), scope, scope_id)).fetchone():
            raise ValueError("This exact memory was suppressed; it cannot be learned again automatically")
        key = content_hash(encode([scope, scope_id, normalize(subject), normalize(content)]))
        with self.transaction():
            row = self.conn.execute("SELECT id FROM facts WHERE validity='active' AND normalized_key=?", (key,)).fetchone()
            if row is None:
                # Legacy rows have no dedup key; compare only exact normalized
                # values within the same scope, never similarity or subject alone.
                rows = self.conn.execute("SELECT id,subject,content FROM facts WHERE validity='active' AND scope=? AND scope_id=?",
                                         (scope, scope_id)).fetchall()
                row = next((r for r in rows if normalize(r["subject"]) == normalize(subject)
                            and normalize(r["content"]) == normalize(content)), None)
            if row:
                memory_id = row["id"]
                if supersedes is not None:
                    self.conn.execute("UPDATE facts SET source='correction',supersedes=?,updated_at=datetime('now') WHERE id=?",
                                      (supersedes, memory_id))
            else:
                memory_id = self.conn.execute(
                    "INSERT INTO facts(subject,content,source,scope,scope_id,learned_session_id,normalized_key,supersedes,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
                    (subject, content, source, scope, scope_id, learned_session or self.session_id, key, supersedes),
                ).lastrowid
            self.evidence("fact", memory_id, sources)
        return memory_id

    @serialized
    def change(self, kind, memory_id, content=None, subject=None):
        table = "facts" if kind == "fact" else "episodes"
        column = "content" if kind == "fact" else "summary"
        where, args = self.visible_sql()
        with self.transaction():
            row = self.conn.execute(f"SELECT * FROM {table} WHERE id=? AND {where}", (memory_id, *args)).fetchone()
            if row is None:
                return False
            if content is not None and normalize(content) == normalize(row[column]):
                if subject is not None:
                    if not subject.strip():
                        raise ValueError("A memory needs a non-empty subject")
                    self.conn.execute("UPDATE facts SET subject=?,normalized_key=NULL,updated_at=datetime('now') WHERE id=?",
                                      (subject.strip().lower(), memory_id))
                return True
            if content is not None and not content.strip():
                raise ValueError("A corrected memory cannot be empty")
            reason = "superseded" if content is not None else "suppressed"
            self.conn.execute(f"UPDATE {table} SET validity=?,updated_at=datetime('now') WHERE id=?", (reason, memory_id))
            # Provenance is incomplete in pre-V3 data. Quarantine the existing
            # transcript and derived episodes conservatively; never erase it.
            self.conn.execute("UPDATE memory_state SET generation=generation+1,export_dirty=1,"
                              "chat_cutoff=(SELECT coalesce(max(id),0) FROM chat_log),"
                              "message_cutoff=(SELECT coalesce(max(id),0) FROM session_messages) WHERE id=1")
            generation = self.generation
            self.conn.execute("INSERT OR REPLACE INTO memory_suppressions VALUES (?,?,?,?,?,?,?)",
                              (kind, row["id"], content_hash(row[column]), row["scope"], row["scope_id"], reason, generation))
            if self.turn_id:
                self.conn.execute("INSERT OR IGNORE INTO memory_blocked_turns VALUES (?)", (self.turn_id,))
            self.conn.execute("UPDATE episodes SET validity='suppressed' WHERE validity='active'")
            self.conn.execute("UPDATE facts SET validity='suppressed' WHERE source='consolidation' AND validity='active'")
            # Exact copies cannot survive through another explicit record.
            for other in self.conn.execute("SELECT id,content FROM facts WHERE validity='active'").fetchall():
                if normalize(row[column]) == normalize(other["content"]):
                    self.conn.execute("UPDATE facts SET validity='suppressed' WHERE id=?", (other["id"],))
            if content is not None:
                replacement = self.add(subject or row["subject"], content, "correction", scope=(row["scope"], row["scope_id"]),
                                       supersedes=row["id"], sources=[("memory", row["id"])])
                # The old exchange remains quarantined. Its replacement has a
                # separate durable link so checkpoints can project only current values.
                turn_id = self.turn_id
                if not turn_id:
                    turn_id = "memory-" + uuid4().hex
                    self.conn.execute(
                        "INSERT INTO session_messages(session_id,turn_id,position,role,content_json,source) "
                        "VALUES (?,?,0,'assistant',?,'memory_correction')",
                        (self.session_id, turn_id, encode("Memory correction saved.")))
                self.evidence("fact", replacement, [("correction_turn", turn_id)])
        try:
            self.after_change()
        except Exception as exc:
            raise TurnStopped("Memory suppression was saved, but its readable export could not be refreshed. "
                              "Repair the export before continuing.") from exc
        return True

    def eligible_turn(self, turn_id):
        if not turn_id:
            return True
        if self.conn.execute("SELECT 1 FROM memory_blocked_turns WHERE turn_id=?", (turn_id,)).fetchone():
            return False
        cutoff = self.conn.execute("SELECT message_cutoff FROM memory_state WHERE id=1").fetchone()[0]
        return not self.conn.execute("SELECT 1 FROM session_messages WHERE turn_id=? AND id<=?", (turn_id, cutoff)).fetchone()

    def eligible_chat(self, row):
        cutoff = self.conn.execute("SELECT chat_cutoff FROM memory_state WHERE id=1").fetchone()[0]
        return row["id"] > cutoff and self.eligible_turn(row["turn_id"])

    def clean_text(self, text, supersedes=None):
        """Exclude exact stale text from instructions and new tool observations.

        Historical paraphrases are excluded by source groups, not this match.
        Originals remain in the archive; tombstones contain only identifiers.
        """
        if not self.generation:
            return text
        values = self.conn.execute("SELECT content AS text FROM facts WHERE validity!='active' AND id!=? UNION ALL "
                                   "SELECT summary AS text FROM episodes WHERE validity!='active'", (supersedes or -1,)).fetchall()
        blocked = [normalize(r["text"]) for r in values if r["text"].strip()]
        inspected = normalize(text)
        # Explicit replacement values can contain the old phrase (for example,
        # a clarified constraint). Shield only the complete current value.
        active, params = self.visible_sql()
        for row in self.conn.execute(f"SELECT content FROM facts WHERE source='correction' AND {active}", params):
            inspected = inspected.replace(normalize(row["content"]), "[current correction]")
        if any(re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", inspected) for value in blocked):
            return "[Content withheld by memory suppression policy.]"
        return text

    def clean_value(self, value, protocol=True):
        if isinstance(value, str):
            return self.clean_text(value)
        if isinstance(value, list):
            return [self.clean_value(v, protocol) for v in value]
        if isinstance(value, dict):
            # Protocol identifiers must survive even when a forgotten value
            # happens to equal a role, tool name or provider call identifier.
            structural = {"type", "role", "id", "name", "tool_use_id"} if protocol and ("type" in value or "role" in value) else set()
            return {k: v if k in structural else self.clean_value(v, protocol and k != "input") for k, v in value.items()}
        return value
