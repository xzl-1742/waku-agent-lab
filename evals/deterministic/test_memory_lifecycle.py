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
