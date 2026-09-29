"""The human memory editor uses the same stores and suppression policy."""

from types import SimpleNamespace

import pytest

from evals.helpers import ScriptedClient, make_waku
from waku.memory import Memory
from waku.ops import dashboard


@pytest.mark.parametrize("record_id", [7, "0007", 'opaque-"quote'])
def test_dashboard_crud_keeps_selected_backend_ids(tmp_path, monkeypatch, record_id):
    app = make_waku(tmp_path, client=ScriptedClient([]))
    app.settings.semantic_store = "mem0"
    calls = []
    facts = SimpleNamespace(
        list=lambda *args: [{"id": record_id, "subject": "remote", "content": "Remote content"}],
        update=lambda *args: calls.append(("update", *args)) or True,
        delete=lambda value: calls.append(("delete", value)) or True,
    )
    monkeypatch.setattr(dashboard, "load_settings", lambda: app.settings)
    monkeypatch.setattr(dashboard.browser_agent, "current", lambda: None)
    monkeypatch.setattr(Memory, "_make_fact_store", staticmethod(lambda conn, settings: facts))
    assert dashboard.memory_action({"action": "update_fact", "id": record_id, "content": "New"}) == {"ok": True}
    assert dashboard.memory_action({"action": "delete_fact", "id": record_id}) == {"ok": True}
    assert calls == [("update", record_id, "New", None), ("delete", record_id)]
    assert "Remote content" in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")


def test_dashboard_deletion_invalidates_live_agent_context(tmp_path, monkeypatch):
    app = make_waku(tmp_path, client=ScriptedClient([]), memory_policy="lifecycle", memory_scope="session")
    app.session.start_new("browser-session")
    old = app.memory.facts.add("project", "Old browser fact")
    app.memory.log_chat("Old browser fact", "A derived response", "browser-session")
    monkeypatch.setattr(dashboard, "load_settings", lambda: app.settings)
    monkeypatch.setattr(dashboard.browser_agent, "current", lambda: app)
    assert dashboard.memory_action({"action": "delete_fact", "id": old}) == {"ok": True}
    app.session.switch("browser-session")
    assert app.session.history == []
    assert app.memory.facts.list() == []
    assert "Old browser fact" not in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")


def test_gather_reads_selected_fact_store(tmp_path, monkeypatch):
    from waku.ops.gather import _memory

    app = make_waku(tmp_path, client=ScriptedClient([]))
    app.settings.semantic_store = "mem0"
    remote = SimpleNamespace(search=lambda query, limit: ["Remote project release"])
    monkeypatch.setattr(Memory, "_make_fact_store", staticmethod(lambda conn, settings: remote))
    assert _memory(app.settings) == "Remote project release"


def test_gather_rejects_sources_collected_before_forgetting(tmp_path, monkeypatch):
    from waku.graph import run_graph
    from waku.ops import gather
    from waku.runtime.context import TurnStopped

    app = make_waku(tmp_path, client=ScriptedClient([]), memory_policy="lifecycle")
    old = app.memory.facts.add("project", "Old project fact")
    graph = gather.build_bound_graph(app)
    app.memory.facts.delete(old)
    monkeypatch.setattr(gather, "_github", lambda settings: {"gh_text": "stale", "gh_open_prs": 1})
    monkeypatch.setattr(gather, "_calendar", lambda settings: {"cal_text": "stale", "cal_event_count": 0})
    for name in ("_web", "_memory"):
        monkeypatch.setattr(gather, name, lambda settings: "Stale scanned data")
    with pytest.raises(TurnStopped, match="fresh scan"):
        run_graph(graph, {})
    assert list((tmp_path / "outbox").glob("gather-*.md")) == []
