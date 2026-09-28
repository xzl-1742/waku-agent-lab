"""Checkpoint publication preserves provenance, session isolation and raw data."""

import json

import pytest

from waku.db import connect
from waku.runtime.checkpoints import FIELDS, CheckpointStore, validate_summary
from waku.runtime.context import TurnStopped
from waku.runtime.records import ExecutionStore


def task_summary(source_id, text="Keep the budget under 50"):
    return {name: ([{"text": text, "source_ids": [source_id]}] if name == "constraints" else [])
            for name in FIELDS}


def store_at(path):
    path.mkdir(exist_ok=True)
    return CheckpointStore(ExecutionStore(connect(path), path, 1024))


def add_turn(store, session="a", text="Keep the budget under 50"):
    record = store.records.turn(session, "eval")
    record.message("user", text)
    record.message("assistant", "Understood")
    return store.sources(session)[-1]


def test_checkpoint_cas_and_restart(tmp_path):
    store = store_at(tmp_path)
    first = add_turn(store)
    second = add_turn(store)
    summary = task_summary(first.rows[0]["id"])
    checkpoint = store.publish("a", None, first.last_id, second.rows[0]["id"], summary, {})
    assert checkpoint["revision"] == 1
    assert store.latest("b") is None
    with pytest.raises(TurnStopped, match="newer revision"):
        store.publish("a", None, second.last_id, None, summary, {})
    store.conn.close()
    restored = store_at(tmp_path)
    assert restored.latest("a") == checkpoint
    assert [t.last_id for t in restored.sources("a", checkpoint["covered_through"])] == [second.last_id]
    assert restored.conn.execute("SELECT count(*) FROM session_messages").fetchone()[0] == 4


@pytest.mark.parametrize("invalid", [None, {}, {key: [] for key in FIELDS},
                                     task_summary(999), task_summary(1, "x" * 5000),
                                     task_summary(True)])
def test_rejects_invalid_summary(invalid):
    with pytest.raises(ValueError):
        validate_summary(invalid, {1})


def test_tool_pairs_and_originals_survive_reload(tmp_path):
    store = store_at(tmp_path)
    record = store.records.turn("a", "eval")
    record.message("user", "Get output")
    for i in range(2):
        record.message("assistant", [{"type": "tool_use", "id": "reused", "name": "read",
                                       "input": {}, "extra_content": {"signature": "keep"}}])
        result_id = record.begin("reused", "read", {})
        full = f"part {i} " + "x" * 10000
        record.finish(result_id, full)
        record.message("user", [{"type": "tool_result", "tool_use_id": "reused", "content": full}])
    record.message("assistant", "Done")
    turn = store.sources("a")[0]
    assert turn.messages[1]["content"][0]["extra_content"]["signature"] == "keep"
    refs = [json.loads(turn.messages[i]["content"][0]["content"])["result_id"] for i in (2, 4)]
    assert len(set(refs)) == 2
    assert len(turn.rows[2]["content_json"]) > 10000
    assert len(turn.messages[2]["content"][0]["content"]) <= 1024


def test_unknown_outcome_blocks_only_own_session(tmp_path):
    store = store_at(tmp_path)
    record = store.records.turn("a", "eval")
    record.message("user", "Send it")
    unknown = record.begin("call", "send", {})
    with pytest.raises(TurnStopped, match=unknown):
        store.sources("a")
    assert store.sources("b") == []


def test_legacy_import_is_idempotent_and_preserves_text(tmp_path):
    store = store_at(tmp_path)
    store.conn.execute("INSERT INTO chat_log (session_id,role,content) VALUES ('a','user','legacy')")
    store.conn.execute("INSERT INTO chat_log (session_id,role,content) VALUES ('a','assistant','[tools used: old]')")
    store.conn.commit()
    store.import_legacy("a")
    store.import_legacy("a")
    turn = store.sources("a")[0]
    assert turn.messages == [{"role": "user", "content": "legacy"},
                             {"role": "assistant", "content": "[tools used: old]"}]
    assert turn.rows[0]["source"].startswith("chat_log:")
