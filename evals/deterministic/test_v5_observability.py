"""Observable evidence stays attributed, bounded and honest across sessions."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from evals.helpers import ScriptedClient, make_waku, response, text_block
from waku.ops.observability import group_turns, projection


def test_interleaved_turns_do_not_share_evidence():
    events = [{"type": "turn_start", "turn_id": "a", "session_id": "one"},
              {"type": "turn_start", "turn_id": "b", "session_id": "two"},
              {"type": "gate", "turn_id": "a", "decision": "retrieve"},
              {"type": "model_call", "turn_id": "b", "model": "small"},
              {"type": "turn_end", "turn_id": "a", "reply": "one"},
              {"type": "turn_end", "turn_id": "b", "reply": "two"}]
    a, b = group_turns(events)
    assert a["reply"] == "one" and not a["model_calls"]
    assert b["reply"] == "two" and b["gate"] is None


def test_projection_bounds_history_and_hides_trace_content(tmp_path):
    app = make_waku(tmp_path, client=ScriptedClient([]))
    events = [{"type": "retrieval", "session_id": "one", "status": "complete", "delivered_ids": [["fact", 1]],
               "secret_text": "not projected"}] * 125
    data = projection(events, app.conn, app.settings)
    assert len(data["events"]) == 100 and "secret_text" not in data["events"][0]
    (tmp_path / "comparison_report.json").write_text("{bad")
    assert projection([], app.conn, app.settings)["comparison"]["status"] == "invalid"
    (tmp_path / "comparison_report.json").write_text("[]")
    assert projection([], app.conn, app.settings)["comparison"]["status"] == "invalid"


@pytest.mark.parametrize("context", ["window", "budget", "compact"])
def test_disable_and_reenable_combined_policies_preserves_suppression(tmp_path, context):
    app = make_waku(tmp_path, client=ScriptedClient([]), context_policy="compact", memory_policy="lifecycle", retrieval_policy="selective")
    record = app.memory.facts.add("private", "V5 forgotten sentinel")
    app.memory.facts.delete(record)
    app.conn.close()
    for retrieval, memory in (("legacy", "legacy"), ("selective", "lifecycle")):
        app = make_waku(tmp_path, client=ScriptedClient([]), context_policy=context, memory_policy=memory, retrieval_policy=retrieval)
        assert app.memory.facts.list() == []
        if app.memory.retrieval:
            assert app.memory.retrieval.rows("sentinel") == []
        assert app.conn.execute("SELECT content FROM facts WHERE id=?", (record,)).fetchone()[0] == "V5 forgotten sentinel"
        assert app.memory.lifecycle.generation > 0
        app.conn.close()


def test_partial_migration_retries_without_losing_records(tmp_path):
    import sqlite3

    from waku.db import SCHEMA, _migrate, connect

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("ALTER TABLE facts ADD COLUMN scope "):
                raise sqlite3.OperationalError("synthetic migration interruption")
            return super().execute(sql, *args, **kwargs)
    conn = sqlite3.connect(tmp_path / "state.db", factory=FailingConnection)
    conn.executescript("CREATE TABLE facts(id INTEGER PRIMARY KEY,subject TEXT,content TEXT,source TEXT,created_at TEXT);"
                       "INSERT INTO facts VALUES(7,'legacy','original data','user','2026');")
    conn.executescript(SCHEMA)
    with pytest.raises(sqlite3.OperationalError):
        _migrate(conn)
    conn.close()
    conn = connect(tmp_path)
    assert conn.execute("SELECT content FROM facts WHERE id=7").fetchone()[0] == "original data"
    assert conn.execute("SELECT scope FROM facts WHERE id=7").fetchone()[0] == "global"
    conn.close()


def test_competing_sessions_keep_scope_and_trace_identity(tmp_path):
    def run(session):
        gate = json.dumps({"retrieve": False, "query": "", "reason": "general", "mode": "search"})
        app = make_waku(tmp_path, client=ScriptedClient([response([text_block(gate)]), response([text_block(session)])]),
                        context_policy="compact", memory_policy="lifecycle", retrieval_policy="selective", consolidate_every=10000)
        app.session.start_new(session)
        app.memory.lifecycle.add("work", f"{session} detail", scope=("session", session))
        try:
            assert app.respond("Hello").reply == session
            assert len(app.memory.retrieval.rows("detail")) == 1
        finally:
            app.conn.close()
    # Initialize migrations before testing competing gateway sessions.
    initial = make_waku(tmp_path, client=ScriptedClient([]))
    initial.conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, ["one", "two"]))
    ledger = [json.loads(line) for line in (tmp_path / "usage.jsonl").read_text().splitlines()]
    assert {r["session_id"] for r in ledger} == {"one", "two"}
    assert len({r["turn_id"] for r in ledger}) == 2


def test_parallel_graph_nodes_keep_call_context_without_leaking_between_nodes():
    from waku.graph.engine import START, Graph, Node, run_graph
    from waku.ops.accounting import call_context

    graph = Graph("attribution")
    def node(state):
        context = call_context.get()
        call_context.set({"session_id": "node-local"})
        return {state["_key"]: context} if "_key" in state else {}
    def observe(key):
        return lambda state: node({**state, "_key": key})
    for key in ("left", "right"):
        graph.add_node(Node(key, observe(key)))
        graph.add_edge(START, key)
    token = call_context.set({"session_id": "session", "turn_id": "turn"})
    try:
        result = run_graph(graph, {})
        assert result["left"] == result["right"] == {"session_id": "session", "turn_id": "turn"}
        assert call_context.get()["session_id"] == "session"
    finally:
        call_context.reset(token)
