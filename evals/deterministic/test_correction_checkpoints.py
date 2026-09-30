"""Current corrections survive revisions without restoring quarantined context."""

import json

import pytest

from evals.deterministic.test_compaction import SummaryClient
from evals.helpers import make_waku, response, tool_block


def background(app, count=8):
    for _ in range(count):
        record = app.records.turn("default", "eval")
        record.message("user", "What is 2+2?")
        record.message("assistant", "4")


@pytest.mark.parametrize("tool_edit", [True, False])
def test_current_correction_survives_revisions_restart_and_unrelated_deletion(tmp_path, tool_edit):
    client = SummaryClient()
    settings = {"memory_policy": "lifecycle", "context_policy": "compact", "consolidate_every": 10000}
    app = make_waku(tmp_path, client=client, **settings)
    old = app.memory.facts.add("budget", "Budget is 900 units")
    if tool_edit:
        client.answers = [response([tool_block("manage_memory", {"action": "update", "id": old, "content": "Budget is 350 units"})])]
        app.respond("Correction: budget is 350 units, replacing 900.")
    else:
        app.memory.facts.update(old, "Budget is 350 units")
    archives = [tuple(r) for r in app.conn.execute("SELECT * FROM session_messages")]
    for revision in (1, 2):
        background(app)
        assert f"checkpoint {revision}" in app.compact().reply
        summary = app.checkpoints.latest("default")["summary_json"]
        assert "350 units" in summary and "900" not in summary
    app.conn.close()
    app = make_waku(tmp_path, client=client, **settings)
    unrelated = app.memory.facts.add("other", "Unrelated disposable statement")
    app.memory.facts.delete(unrelated)
    background(app)
    assert "checkpoint 3" in app.compact().reply
    assert "350 units" in app.checkpoints.latest("default")["summary_json"]
    current = next(f for f in app.memory.facts.list() if f["subject"] == "budget")
    app.memory.facts.update(current["id"], "Budget is 275 units")
    background(app)
    assert "checkpoint 4" in app.compact().reply
    summary = app.checkpoints.latest("default")["summary_json"]
    assert "275 units" in summary and "350 units" not in summary and "900" not in summary
    app.memory.facts.delete(next(f["id"] for f in app.memory.facts.list() if f["subject"] == "budget"))
    background(app)
    assert "checkpoint 5" in app.compact().reply
    assert "units" not in app.checkpoints.latest("default")["summary_json"]
    assert [tuple(r) for r in app.conn.execute("SELECT * FROM session_messages ORDER BY id LIMIT ?", (len(archives),))] == archives


def test_correction_projection_does_not_cross_session_or_project(tmp_path):
    app = make_waku(tmp_path, client=SummaryClient(), memory_policy="lifecycle", context_policy="compact", project_id="alpha")
    old = app.memory.lifecycle.add("budget", "Budget is 900 units", scope=("project", "alpha"))
    app.memory.facts.update(old, "Budget is 350 units")
    assert "350" in json.dumps([t.messages for t in app.checkpoints.sources("default")])
    assert app.checkpoints.sources("another") == []
    app.settings.project_id = "beta"
    assert app.checkpoints.sources("default") == []
