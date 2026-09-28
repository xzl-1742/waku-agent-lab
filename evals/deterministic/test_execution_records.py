"""Durable tool receipts outlive prompt reduction and enforce session access."""

import hashlib
import json
from pathlib import Path

import pytest

from waku.db import connect
from waku.runtime.context import TurnStopped
from waku.runtime.records import ExecutionStore, reduce_output


def store(tmp_path, cap=1024):
    return ExecutionStore(connect(tmp_path), tmp_path, cap)


def test_migration_is_additive_and_reopen_keeps_original_records(tmp_path):
    first = store(tmp_path)
    first.conn.execute("INSERT INTO facts(subject,content) VALUES ('alex','original fact')")
    first.conn.commit()
    turn = first.turn("s", "eval")
    turn.message("user", "remember this")
    rid = turn.begin("call-1", "test", {"arg": "中文"})
    assert first.conn.execute("SELECT state FROM tool_executions").fetchone()[0] == "pending"
    original = "中文 log " * 3000 + "\nReceipt: A-17\nSaved locally; nothing was sent."
    visible = turn.finish(rid, original)
    assert len(visible.encode()) <= 1024
    assert "A-17" in visible and "nothing was sent" in visible
    assert first.path(rid).read_text(encoding="utf-8") == original
    first.conn.close()
    reopened = store(tmp_path)
    assert reopened.conn.execute("SELECT content FROM facts").fetchone()[0] == "original fact"
    assert reopened.conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 1
    row = reopened.conn.execute("SELECT * FROM tool_executions").fetchone()
    assert row["state"] == "complete"
    assert row["result_sha256"] == hashlib.sha256(original.encode()).hexdigest()
    assert json.loads(row["args_json"]) == {"arg": "中文"}


def test_result_paging_reconstructs_unicode_and_is_always_bounded(tmp_path):
    records = store(tmp_path)
    turn = records.turn("s", "eval")
    rid = turn.begin("call", "fixture", {})
    original = '中文🙂\n"\\\t' * 80
    turn.finish(rid, original)
    parts, offset = [], 0
    while True:
        text = records.read("s", rid, offset, 999999)
        assert len(text.encode()) <= records.output_cap
        page = json.loads(text)
        parts.append(page["content"])
        offset = page["next_offset"]
        if page["eof"]:
            break
    assert "".join(parts) == original
    assert json.loads(records.read("s", rid, offset))["content"] == ""


def test_result_ids_and_session_authority_are_not_paths(tmp_path):
    records = store(tmp_path)
    turn = records.turn("owner", "eval")
    rid = turn.begin("call", "fixture", {})
    with pytest.raises(ValueError, match="unknown"):
        records.read("owner", rid)
    turn.finish(rid, "original")
    with pytest.raises(ValueError, match="active session"):
        records.read("other", rid)
    for invalid in ("../SOUL.md", "C:/private", "f" * 31, 123):
        with pytest.raises(ValueError, match="result ID"):
            records.read("owner", invalid)
    for offset, limit in ((-1, 1), (0, 0), (False, 1), (0, "100"), (999, 1)):
        with pytest.raises(ValueError):
            records.read("owner", rid, offset, limit)


def test_result_write_failure_leaves_pending_outcome(tmp_path, monkeypatch):
    records = store(tmp_path)
    turn = records.turn("s", "eval")
    rid = turn.begin("call", "side_effect", {})
    real_open = Path.open

    def fail(path, *args, **kwargs):
        if path.name == f"{rid}.txt":
            raise OSError("synthetic disk failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(TurnStopped, match="outcome is unknown"):
        turn.finish(rid, "the action already happened")
    assert records.conn.execute("SELECT state FROM tool_executions").fetchone()[0] == "pending"


def test_small_outputs_remain_identical_and_json_tail_fields_survive():
    assert reduce_output("Saved.", "a" * 32, 1024) == "Saved."
    output = json.dumps({"log": "x" * 10000, "id": "receipt-123", "status": "partial",
                         "error": "remote sync failed", "sent": False})
    visible = reduce_output(output, "a" * 32, 1024)
    data = json.loads(visible)
    assert len(visible.encode()) <= 1024
    assert "receipt-123" in visible and "remote sync failed" in visible
    assert data["action_success"] == "unverified"


def test_linked_result_directory_is_rejected_before_io(tmp_path, monkeypatch):
    records = store(tmp_path)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path.name == "results" or original(path))
    with pytest.raises(ValueError, match="cannot be a link"):
        records.path("a" * 32)
