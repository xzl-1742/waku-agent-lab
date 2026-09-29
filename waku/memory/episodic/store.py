"""Episodic memory — dated events: what happened, and when.

Semantic memory answers "what do I know?"; episodic answers "what happened
last Tuesday?". Same SQLite file, but every row carries a date and retrieval
blends relevance (FTS rank) with recency — the whiteboard's "RAG for
relevance + SQL for recency".
"""

from __future__ import annotations

import sqlite3

from waku.memory.semantic.store import _fts_query


class SqliteEpisodeStore:
    def __init__(self, conn: sqlite3.Connection, lifecycle=None):
        self.conn = conn
        self.lifecycle = lifecycle

    def _visible(self, alias=""):
        if self.lifecycle:
            return self.lifecycle.visible_sql(alias)
        p = alias + "." if alias else ""
        return f"{p}validity='active' AND {p}scope='global'", ()

    def add(self, summary: str, happened_at: str) -> None:
        self.conn.execute(
            "INSERT INTO episodes (happened_at, summary) VALUES (?,?)",
            (happened_at, summary),
        )
        self.conn.commit()

    def search(self, query: str, top_k: int = 3) -> list[str]:
        """Relevance first (FTS), most recent first among matches."""
        fts = _fts_query(query)
        if not fts:
            return self.recent(top_k)
        visible, params = self._visible("e")
        rows = self.conn.execute(
            "SELECT e.happened_at, e.summary FROM episodes_fts JOIN episodes e "
            f"ON e.id = episodes_fts.rowid WHERE episodes_fts MATCH ? AND {visible} "
            "ORDER BY rank, e.happened_at DESC LIMIT ?",
            (fts, *params, top_k),
        ).fetchall()
        return [f"({r['happened_at']}) {r['summary']}" for r in rows]

    def recent(self, top_k: int = 3) -> list[str]:
        visible, params = self._visible()
        rows = self.conn.execute(
            f"SELECT happened_at, summary FROM episodes WHERE {visible} ORDER BY happened_at DESC LIMIT ?",
            (*params, top_k),
        ).fetchall()
        return [f"({r['happened_at']}) {r['summary']}" for r in rows]

    def list(self, limit: int = 200) -> list[dict]:
        visible, params = self._visible()
        rows = self.conn.execute(
            f"SELECT * FROM episodes WHERE {visible} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, episode_id: int) -> bool:
        if self.lifecycle and self.lifecycle.enabled:
            return self.lifecycle.change("episode", episode_id)
        cur = self.conn.execute("DELETE FROM episodes WHERE id=?", (episode_id,))
        self.conn.commit()
        return cur.rowcount > 0
