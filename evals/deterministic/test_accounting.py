"""Accounting preserves attempts, partial usage and the dispatch boundary."""

import json
from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest

from evals.helpers import ScriptedClient, make_waku, response, text_block
from waku.loop.models import OpenAICompatClient
from waku.ops.accounting import UsageClient, model_stage, usage_fields
from waku.runtime.context import ContextBudget, ContextOverflow, guard_client


def metered(client):
    rows = []
    return UsageClient(client, NS(provider="test"), rows.append), rows


@pytest.mark.parametrize("usage,expected", [(None, (None, None)),
    (NS(input_tokens=0, output_tokens=0), (0, 0)),
    (NS(input_tokens=0, output_tokens=0, measured=False), (None, None)),
    (NS(input_tokens=12), (12, None))])
def test_usage_distinguishes_missing_partial_zero(usage, expected):
    fields = usage_fields(usage)
    assert (fields["in"], fields["out"]) == expected


def test_openai_retry_and_parse_failure_preserve_raw_usage():
    adapter = object.__new__(OpenAICompatClient)
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ValueError("unsupported max_completion_tokens")
        return NS(usage=NS(prompt_tokens=20, completion_tokens=4, prompt_tokens_details=NS(cached_tokens=8)),
                  choices=[NS(message=NS(content=None, tool_calls=[NS(id="a", function=NS(name="tool", arguments="{bad"))]))])
    adapter._client = NS(chat=NS(completions=NS(create=create)))
    adapter.messages = NS(create=adapter._create)
    client, rows = metered(adapter)
    with model_stage("answer"), pytest.raises(ValueError):
        client.messages.create(model="chosen", messages=[], max_tokens=20)
    assert len(rows) == 2
    assert [r["status"] for r in rows] == ["failed", "complete"]
    assert rows[1]["in"] == 20 and rows[1]["cache_read_input_tokens"] == 8
    assert rows[0]["operation_id"] == rows[1]["operation_id"]
    assert rows[0]["model"] == "chosen" and rows[0]["stage"] == "answer"


def test_preflight_rejection_records_no_call():
    client, rows = metered(ScriptedClient([]))
    guarded = guard_client(client, ContextBudget(main_model="test", capacity=4096))
    with pytest.raises(ContextOverflow):
        guarded.messages.create(model="test", messages=[{"role": "user", "content": "x" * 10000}], max_tokens=100)
    assert rows == []


def test_stream_finalization_is_once_and_failure_is_separate():
    message = response([text_block("answer")])
    message.usage = NS(input_tokens=20, output_tokens=3)
    @contextmanager
    def stream(**kwargs):
        yield NS(text_stream=iter(["answer"]), get_final_message=lambda: message)
    raw = NS(messages=NS(stream=stream, create=lambda **kwargs: message))
    client, rows = metered(raw)
    with client.messages.stream(model="small") as result:
        assert list(result.text_stream) == ["answer"]
        assert result.get_final_message() is result.get_final_message()
    assert len(rows) == 1 and rows[0]["in"] == 20
    @contextmanager
    def broken(**kwargs):
        raise OSError("synthetic stream failure")
        yield
    raw.messages.stream = broken
    with pytest.raises(OSError), client.messages.stream(model="small"):
        pass
    client.messages.create(model="small")
    assert [r["status"] for r in rows] == ["complete", "failed", "complete"]


def test_calls_include_gate_and_judge_without_observer_duplicates(tmp_path):
    script = ScriptedClient([response([text_block('{"retrieve":false,"query":"","reason":"general"}')]),
                             response([text_block("hello")]), response([text_block("pass")])])
    app = make_waku(tmp_path, client=script, model="main", small_model="small", consolidate_every=10000)
    app.respond("hello", observer=lambda kind, event: None)
    with model_stage("judge", scope="judge"):
        app.client.messages.create(model="referee", messages=[], max_tokens=20)
    rows = [json.loads(line) for line in (tmp_path / "usage.jsonl").read_text().splitlines()]
    assert [r["stage"] for r in rows] == ["gate", "answer", "judge"]
    assert [r["model"] for r in rows] == ["small", "main", "referee"]
    assert rows[0]["turn_id"] == rows[1]["turn_id"]
    assert rows[2]["scope"] == "judge" and rows[0]["in"] is None


def test_cached_openai_usage_not_counted_twice_in_context():
    budget = ContextBudget(main_model="test")
    result = NS(usage=NS(input_tokens=1000, output_tokens=2, cache_read_input_tokens=800,
                         cache_included_in_input=True))
    observed = budget.observe({"model": "test", "messages": []}, result)
    assert observed["observed_input_tokens"] == 1000


def test_paid_response_survives_memory_discard(tmp_path):
    app = make_waku(tmp_path, client=ScriptedClient([]), memory_policy="lifecycle")
    # The response arrives before a generation change is detected by the guard.
    usage_client = app.client.client.client
    def create(**kwargs):
        app.conn.execute("UPDATE memory_state SET generation=generation+1")
        app.conn.commit()
        return NS(usage=NS(input_tokens=12, output_tokens=2))
    usage_client.client.messages.create = create
    with pytest.raises(RuntimeError, match="Memory changed"):
        app.client.messages.create(model="main", messages=[], max_tokens=20)
    rows = [json.loads(line) for line in (tmp_path / "usage.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["in"] == 12


def test_unconsumed_adapter_stream_has_no_dispatch():
    adapter = object.__new__(OpenAICompatClient)
    adapter.messages = NS(stream=adapter._stream)
    client, rows = metered(adapter)
    with client.messages.stream(model="test", messages=[], max_tokens=20):
        pass
    assert rows == []


def test_strict_totals_preserve_unknown_cost_and_separate_judge():
    from waku.ops.usage import summarize

    rows = [{"provider": "p", "model": "m", "in": 100, "out": 10, "stage": "gate"},
            {"in": None, "out": None, "status": "failed", "stage": "answer"},
            {"in": 40, "out": 2, "scope": "judge"}]
    result = summarize(rows)
    assert result["runtime"]["calls"] == 2
    assert result["runtime"]["input_tokens"] is None
    assert result["runtime"]["known_input_tokens"] == 100
    assert result["runtime"]["cost_usd"] is None
    assert result["judge"]["calls"] == 1
    priced = summarize(rows[:1], {("p", "m"): {"input": 1, "output": 2, "source": "synthetic test rate"}})
    assert priced["runtime"]["cost_usd"] == pytest.approx(0.00012)
