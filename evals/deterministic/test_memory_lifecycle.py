"""Memory policy keeps evidence, store identities and suppression consistent."""

from types import SimpleNamespace

import pytest

from evals.helpers import ScriptedClient, make_waku
from waku.tools.memory_admin import make_manage_memory_tool
from waku.tools.notes import make_tool


@pytest.mark.parametrize("record_id", [7, "uuid-fact", "0007"])
def test_tool_crud_preserves_backend_id(record_id):
    calls = []
    facts = SimpleNamespace(search_with_ids=lambda q, k: [{"id": record_id, "subject": "test", "content": "old"}],
                            update=lambda *args: calls.append(("update", *args)) or True,
                            delete=lambda value: calls.append(("delete", value)) or True)
    tool = make_manage_memory_tool(SimpleNamespace(facts=facts, episodes=facts))
    assert str(record_id) in tool.fn(action="search")
    tool.fn(action="update", id=record_id, content="new")
    tool.fn(action="delete", id=record_id)
    tool.fn(action="delete", kind="episode", id=record_id)
    assert calls == [("update", record_id, "new", None), ("delete", record_id), ("delete", record_id)]


def test_explicit_save_uses_selected_backend(tmp_path):
    app = make_waku(tmp_path, client=ScriptedClient([]))
    calls = []
    app.memory.facts = SimpleNamespace(add=lambda *args, **kwargs: calls.append((args, kwargs)))
    make_tool(app.conn, app.memory).fn("project", "keep this")
    assert calls == [(("project", "keep this"), {"source": "user"})]
    assert app.conn.execute("SELECT count(*) FROM facts").fetchone()[0] == 0


def lifecycle_app(path, **kwargs):
    return make_waku(path, client=ScriptedClient([]), memory_policy="lifecycle", **kwargs)


def test_normalized_exact_dedup_preserves_scope_and_evidence(tmp_path):
    app = lifecycle_app(tmp_path)
    policy = app.memory.lifecycle
    policy.turn_id = "first"
    first = app.memory.facts.add("Project", "Budget   50")
    policy.turn_id = "second"
    assert app.memory.facts.add("PROJECT", "budget 50") == first
    other = app.memory.facts.add("Project", "Budget 51")
    assert other != first
    policy.settings.memory_scope = "session"
    scoped = app.memory.facts.add("Project", "budget 50")
    assert scoped != first
    assert app.conn.execute("SELECT count(*) FROM memory_evidence WHERE memory_id=?", (first,)).fetchone()[0] == 2
    policy.session_id = "elsewhere"
    assert scoped not in [r["id"] for r in app.memory.facts.list()]


def test_correction_preserves_version_and_only_explicit_target(tmp_path):
    app = lifecycle_app(tmp_path)
    old = app.memory.facts.add("project", "Use port 3000")
    unrelated = app.memory.facts.add("other project", "Use port 3001")
    assert app.memory.facts.update(str(old), "Use port 4000")
    rows = app.conn.execute("SELECT * FROM facts ORDER BY id").fetchall()
    assert rows[0]["validity"] == "superseded"
    assert rows[-1]["supersedes"] == old
    assert {r["id"] for r in app.memory.facts.list()} == {unrelated, rows[-1]["id"]}
    assert "3000" not in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "4000" in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert app.conn.execute("SELECT content_hash FROM memory_suppressions").fetchone()[0] != "Use port 3000"


def test_forgetting_survives_restart_and_disabling_new_lifecycle_writes(tmp_path):
    app = lifecycle_app(tmp_path)
    old = app.memory.facts.add("project", "Secret unique sentinel")
    assert app.memory.facts.delete(old)
    app.conn.close()
    app = make_waku(tmp_path, client=ScriptedClient([]), memory_policy="legacy")
    assert app.memory.facts.search("sentinel") == []
    assert app.memory.facts.list() == []
    with pytest.raises(ValueError, match="suppressed"):
        app.memory.facts.add("project", "Secret unique sentinel")
    assert app.conn.execute("SELECT content FROM facts WHERE id=?", (old,)).fetchone()[0] == "Secret unique sentinel"


def test_remote_lifecycle_fails_before_loading_adapter(tmp_path):
    with pytest.raises(ValueError, match="require SQLite"):
        lifecycle_app(tmp_path, semantic_store="supabase")


def test_relabeling_same_content_does_not_suppress_the_fact(tmp_path):
    app = lifecycle_app(tmp_path)
    old = app.memory.facts.add("project", "Budget 50")
    assert app.memory.facts.update(old, "budget 50", "planning")
    assert app.memory.lifecycle.generation == 0
    assert app.memory.facts.list()[0]["subject"] == "planning"
    assert app.memory.facts.add("planning", "Budget 50") == old


def test_suppressed_text_cannot_be_readded_in_another_scope(tmp_path):
    app = lifecycle_app(tmp_path)
    old = app.memory.facts.add("project", "Budget 50")
    assert app.memory.facts.delete(old)
    app.settings.memory_scope = "session"
    app.session.start_new("different")
    with pytest.raises(ValueError, match="suppressed"):
        app.memory.facts.add("another label", "Budget 50")
    assert app.memory.facts.add("project", "Budget 500")


def test_project_scope_filters_before_ranking_and_limit(tmp_path):
    app = lifecycle_app(tmp_path, memory_scope="project", project_id="alpha")
    first = app.memory.facts.add("release", "Alpha release plan")
    app.settings.project_id = "beta"
    for i in range(5):
        app.memory.facts.add("release", f"Beta release plan {i}")
    app.settings.project_id = "alpha"
    assert [r["id"] for r in app.memory.facts.search_with_ids("release", 1)] == [first]
    assert app.memory.facts.update(first, "Revised alpha release plan")
    assert app.memory.lifecycle.clean_text("Revised alpha release plan") == "Revised alpha release plan"
    assert len(app.conn.execute("SELECT * FROM facts WHERE scope_id='beta' AND validity='active'").fetchall()) == 5


def test_additive_migration_preserves_old_ids_and_text(tmp_path):
    import sqlite3

    from waku.db import connect

    conn = sqlite3.connect(tmp_path / "state.db")
    conn.executescript("""
        CREATE TABLE facts(id INTEGER PRIMARY KEY,subject TEXT,content TEXT,source TEXT,created_at TEXT);
        CREATE TABLE episodes(id INTEGER PRIMARY KEY,happened_at TEXT,summary TEXT,created_at TEXT);
        CREATE TABLE chat_log(id INTEGER PRIMARY KEY,role TEXT,content TEXT,consolidated INTEGER,created_at TEXT);
        INSERT INTO facts VALUES(17,'legacy','original text','user','2026-01-01');
        INSERT INTO chat_log VALUES(19,'user','original chat',0,'2026-01-01');
    """)
    conn.close()
    for _ in range(2):
        conn = connect(tmp_path)
        fact = conn.execute("SELECT * FROM facts").fetchone()
        assert (fact["id"], fact["content"], fact["validity"], fact["scope"]) == (17, "original text", "active", "global")
        assert conn.execute("SELECT content FROM chat_log WHERE id=19").fetchone()[0] == "original chat"
        conn.close()


def test_correction_to_existing_value_keeps_a_version_link(tmp_path):
    app = lifecycle_app(tmp_path)
    old = app.memory.facts.add("project", "Port 3000")
    current = app.memory.facts.add("project", "Port 4000")
    assert app.memory.facts.update(old, "Port 4000")
    assert len(app.memory.facts.list()) == 1
    row = app.memory.facts.list()[0]
    assert (row["id"], row["supersedes"], row["source"]) == (current, old, "correction")
