"""DETERMINISTIC EVAL — working memory is a bounded sliding window.

Sean's insight while testing Telegram: its one always-on session accumulated
history forever, and every turn resent the whole thing (unbounded context ->
cost/latency climb -> eventual context-limit break). Working memory must be a
fixed window; older turns live in state.db + consolidation, not the prompt."""

from __future__ import annotations

import pytest

from evals.helpers import ScriptedClient, make_waku, response, text_block


def _gate_skip():
    return response([text_block('{"retrieve": false, "query": "", "reason": "t"}')])


def test_prompt_history_is_windowed(tmp_path, monkeypatch):
    monkeypatch.setenv("WAKU_HISTORY_TURNS", "3")   # keep only last 3 turns
    sent = []

    class Recorder(ScriptedClient):
        def _create(self, **kwargs):
            # snapshot the message count NOW — run_loop mutates the same list
            # (appends the assistant reply) after this call returns
            sent.append(list(kwargs.get("messages", [])))
            return self._script.pop(0)

    # 5 turns; each turn = gate call (skip) + one loop call
    script = []
    for _ in range(5):
        script += [_gate_skip(), response([text_block("ok")])]
    app = make_waku(tmp_path / "home", client=Recorder(script))
    for i in range(5):
        app.respond(f"message number {i}")

    # the LAST loop call's messages: at most 3 turns * 2 rows + the new user
    # message = 7, and it must NOT contain the oldest turns
    last = sent[-1]
    assert len(last) <= 3 * 2 + 1, f"window not applied: {len(last)} messages"
    text_blob = " ".join(str(m.get("content", "")) for m in last)
    assert "message number 0" not in text_blob
    assert "message number 4" in text_blob   # the newest turn is present


def test_default_window_is_generous_but_finite(tmp_path, monkeypatch):
    monkeypatch.delenv("WAKU_HISTORY_TURNS", raising=False)
    app = make_waku(tmp_path / "home", client=ScriptedClient([]))
    assert app.settings.history_turns == 12


def test_zero_window_sends_only_current_message_and_preserves_log(tmp_path):
    sent = []

    class Recorder(ScriptedClient):
        def _create(self, **kwargs):
            if "system" in kwargs:
                sent.append(list(kwargs["messages"]))
            return super()._create(**kwargs)

    app = make_waku(tmp_path / "home", history_turns=0, client=Recorder([
        _gate_skip(), response([text_block("first")]),
        _gate_skip(), response([text_block("second")]),
    ]))
    app.respond("old request")
    app.respond("current request")
    assert sent[-1] == [{"role": "user", "content": "current request"}]
    assert len(list(app.memory.session_history("default"))) == 2
    app.session.switch("default")
    assert app.session.history == []


@pytest.mark.parametrize("from_environment", [True, False])
def test_negative_window_is_rejected(monkeypatch, from_environment):
    from waku.config import Settings

    if from_environment:
        monkeypatch.setenv("WAKU_HISTORY_TURNS", "-1")
    with pytest.raises(ValueError, match="history_turns must be non-negative"):
        Settings(**({} if from_environment else {"history_turns": -1}))
