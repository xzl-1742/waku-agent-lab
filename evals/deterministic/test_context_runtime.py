"""Exercise budgets and durable tool outcomes through production Waku wiring."""

import json
from types import SimpleNamespace

import pytest

from evals.helpers import ScriptedClient, make_waku, response, text_block, tool_block
from waku.runtime.context import ContextBudget, ContextOverflow, plain
from waku.tools.registry import Tool


def skip_gate():
    return response([text_block('{"retrieve": false, "query": "", "reason": "test"}')])


def fixture_tool(app, output, hits=None, name="fixture"):
    def execute():
        if hits is not None:
            hits.append(name)
        return output
    app.tools.register(Tool(name, "Synthetic local fixture", {"type": "object", "properties": {}}, execute))


def test_large_output_is_bounded_in_loop_history_and_reload(tmp_path):
    sent = []

    class Recorder(ScriptedClient):
        def _create(self, **kwargs):
            sent.append(plain(kwargs))
            return super()._create(**kwargs)

    client = Recorder([skip_gate(), response([tool_block("fixture", {})], "tool_use"),
                       response([text_block("done")]), skip_gate(), response([text_block("still done")])])
    app = make_waku(tmp_path / "home", client=client, tool_output_bytes=1024)
    original = "log " * 20000 + "\nReceipt: xyz123; saved locally, not sent."
    fixture_tool(app, original)
    result = app.respond("perform the fixture")
    assert result.reply == "done"
    assert len(result.tool_calls[0]["output"].encode()) <= 1024
    assert original not in str(sent[-1])
    assert "xyz123" in str(sent[-1])
    saved = app.conn.execute("SELECT content_json FROM session_messages WHERE role='user' ORDER BY id DESC").fetchone()[0]
    assert original in json.loads(saved)[0]["content"]
    rid = result.tool_calls[0]["result_id"]
    app.session.switch("default")
    app.respond("do not repeat the fixture; confirm it")
    assert original not in str(sent[-1])
    assert rid in str(sent[-1])
    assert app.records.path(rid).read_text(encoding="utf-8") == original
    page = json.loads(app.tools.execute("manage_memory", {"action": "read_result", "result_id": rid}))
    assert page["content"] in original
    app.session.start_new("other")
    assert "active session" in app.tools.execute("manage_memory", {"action": "read_result", "result_id": rid})


def test_every_request_including_post_tool_batches_fits(tmp_path):
    calls, events = [], []

    class Recorder(ScriptedClient):
        def _create(self, **kwargs):
            calls.append(plain(kwargs))
            return super()._create(**kwargs)

    client = Recorder([skip_gate(), response([tool_block("fixture", {}, "a"),
                                            tool_block("second", {}, "b")], "tool_use"),
                       response([text_block("done")])])
    app = make_waku(tmp_path / "home", client=client, context_window_tokens=24000,
                    small_context_window_tokens=8000, tool_output_bytes=1024)
    fixture_tool(app, "中文" * 40000)
    fixture_tool(app, "json" * 40000, name="second")
    app.session.add_exchange("old" * 15000, "old answer")
    assert app.respond("read both", observer=lambda k, e: events.append((k, e))).reply == "done"
    for request in calls:
        app.budget.check(request)
    batches = [m for m in calls[-1]["messages"] if isinstance(m["content"], list)
               and m["role"] == "user"]
    assert len(batches[-1]["content"]) == 2
    assert any(e.get("dropped_messages", 0) for k, e in events if k == "context")


def test_oversized_current_input_never_calls_provider(tmp_path):
    client = ScriptedClient([])
    app = make_waku(tmp_path / "home", client=client)
    result = app.respond("x" * 100000)
    assert "Context budget exceeded" in result.reply
    assert client._script == []
    assert app.conn.execute("SELECT COUNT(*) FROM tool_executions").fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["budget", "recording", "provider"])
def test_graph_failure_after_side_effect_cannot_replay_it(tmp_path, monkeypatch, failure):
    script = [response([text_block('{"route":"full","reason":"fixture"}')]), skip_gate(),
              response([tool_block("fixture", {})], "tool_use")]

    class Client(ScriptedClient):
        def _create(self, **kwargs):
            if not self._script:
                raise RuntimeError("provider failed after action")
            return super()._create(**kwargs)

    app = make_waku(tmp_path / "home", client=Client(script), graph_workflows=True)
    hits = []

    def execute():
        hits.append("performed")
        if failure == "budget":
            app.budget.capacity = 100
        elif failure == "recording":
            monkeypatch.setattr(app.records, "path", lambda _: (_ for _ in ()).throw(OSError("disk")))
        return "action already completed"

    app.tools.register(Tool("fixture", "fixture", {"type": "object", "properties": {}}, execute))
    result = app.respond("run once")
    assert len(hits) == 1
    assert ("budget exceeded" in result.reply or "unknown" in result.reply or "no action was repeated" in result.reply)


def test_streaming_checks_budget_before_dispatch_and_keeps_one_call(tmp_path):
    from contextlib import contextmanager

    started = []

    @contextmanager
    def stream(**kwargs):
        started.append(kwargs)
        yield SimpleNamespace(text_stream=iter(["hello"]),
                              get_final_message=lambda: response([text_block("hello")]))

    client = ScriptedClient([skip_gate()])
    client.messages.stream = stream
    app = make_waku(tmp_path / "home", client=client)
    assert app.respond("hello", stream=True).reply == "hello"
    assert len(started) == 1
    app.budget.capacity = 50
    assert "budget exceeded" in app.respond("hello", stream=True).reply
    assert len(started) == 1


def test_direct_graph_llm_node_rejects_large_input():
    from waku.graph import Graph, run_graph
    from waku.graph.engine import END, START
    from waku.graph.nodes import llm_node

    client = ScriptedClient([])
    graph = Graph("bounded")
    graph.add_node(llm_node("answer", "{message}", "reply", client=client, model="unknown"))
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    with pytest.raises(ContextOverflow):
        run_graph(graph, {"message": "x" * 100000})


def test_canonical_assistant_blocks_roundtrip_provider_fields():
    from waku.loop.models import OpenAICompatClient

    block = tool_block("fixture", {"arg": "中文"})
    block.extra = {"google": {"thought_signature": "synthetic"}}
    live = [{"role": "assistant", "content": [text_block("check"), block]}]
    restored = json.loads(json.dumps(plain(live)))
    client = OpenAICompatClient.__new__(OpenAICompatClient)
    kwargs = {"model": "synthetic", "max_tokens": 100}
    assert client._to_openai(messages=live, **kwargs) == client._to_openai(messages=restored, **kwargs)


def test_missing_adapter_usage_cannot_calibrate():
    from waku.loop.models import OpenAICompatClient

    client = OpenAICompatClient.__new__(OpenAICompatClient)
    client._call = lambda *a, **k: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=[]))], usage=None)
    reply = client._create(model="synthetic", messages=[], max_tokens=10)
    assert reply.usage.measured is False
    assert ContextBudget().observe({"messages": []}, reply) is None
