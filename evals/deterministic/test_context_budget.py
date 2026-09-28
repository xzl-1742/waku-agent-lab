"""Request budgets include all prompt parts and preserve complete exchanges."""

from types import SimpleNamespace

import pytest

from evals.helpers import ScriptedClient, response, text_block, tool_block
from waku.config import Settings
from waku.runtime.context import (
    FALLBACK_CAPACITY,
    ContextBudget,
    ContextOverflow,
    estimate_request,
    guard_client,
    plain,
)


def request(messages=None, **extra):
    return {"model": "synthetic", "max_tokens": 100, "system": "rules",
            "tools": [], "messages": messages or [{"role": "user", "content": "hello"}], **extra}


@pytest.mark.parametrize("content", ["中文" * 30, '{"key":"value"}' * 10, "def f():\n    return 42\n" * 20])
def test_estimate_includes_unicode_code_and_json(content):
    base = estimate_request(request())
    assert estimate_request(request(system=content)) >= len(content.encode("utf-8"))
    assert estimate_request(request(tools=[{"description": content}])) > base


def test_unknown_alias_uses_explicit_or_conservative_capacity():
    fallback = ContextBudget.from_settings(Settings(model="unknown-alias"))
    assert fallback.measure(request())["capacity_tokens"] == FALLBACK_CAPACITY
    configured = ContextBudget.from_settings(Settings(context_window_tokens=16000, model="synthetic"))
    assert configured.measure(request())["capacity_tokens"] == 16000
    assert configured.measure(request())["capacity_source"] == "configured"


def test_fit_removes_complete_old_tool_exchange():
    messages = [{"role": "user", "content": "old" * 200},
                {"role": "assistant", "content": [tool_block("a", {}, "a"), tool_block("b", {}, "b")]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": k, "content": "ok"}
                                                for k in ("a", "b")]},
                {"role": "assistant", "content": "done"},
                {"role": "user", "content": "current"}]
    budget = ContextBudget(capacity=1100, margin=100, main_model="synthetic")
    fitted = budget.fit(request(messages))
    assert fitted["dropped_messages"] == 4
    assert messages == [{"role": "user", "content": "current"}]


def test_active_turn_is_pinned_and_rejected_before_dispatch():
    client = ScriptedClient([response([text_block("never called")])])
    guarded = guard_client(client, ContextBudget(capacity=1000, margin=100, main_model="synthetic"))
    req = request([{ "role": "user", "content": "x" * 2000}])
    with pytest.raises(ContextOverflow):
        guarded.context_budget.fit(req)
    with pytest.raises(ContextOverflow):
        guarded.messages.create(**req)
    assert len(client._script) == 1


def test_schema_and_output_reserve_can_exhaust_budget():
    with pytest.raises(ContextOverflow):
        ContextBudget(capacity=1000, main_model="synthetic").check(request(tools=[{"schema": "x" * 1200}]))
    with pytest.raises(ContextOverflow):
        ContextBudget(capacity=1000, margin=100, main_model="synthetic").check(request(max_tokens=950))


def test_capacity_override_cannot_leak_to_an_unrelated_model():
    budget = ContextBudget(capacity=200000, main_model="configured", small_model="small")
    assert budget.measure(request(model="unrelated"))["capacity_tokens"] == FALLBACK_CAPACITY
    same = ContextBudget(capacity=200000, small_capacity=16000,
                         main_model="shared", small_model="shared")
    assert same.measure(request(model="shared"))["capacity_tokens"] == 16000


def test_partial_tool_batch_is_rejected():
    messages = [{"role": "assistant", "content": [tool_block("a", {}, "a")]},
                {"role": "user", "content": "new user input"}]
    with pytest.raises(ContextOverflow, match="paired result"):
        ContextBudget().fit(request(messages))


def test_usage_is_request_specific_and_only_raises_estimate():
    budget = ContextBudget(margin=0)
    req = request()
    before = budget.measure(req)["estimated_input_tokens"]
    observed = budget.observe(req, SimpleNamespace(usage=SimpleNamespace(input_tokens=before * 2)))
    assert budget.measure(req)["estimated_input_tokens"] == before * 2
    assert observed["observed_input_tokens"] == before * 2
    assert budget.observe(req, SimpleNamespace(usage=SimpleNamespace(input_tokens=0))) is None
    req["system"] = "changed" * 100
    assert budget.measure(req)["estimated_input_tokens"] > before * 2
    assert budget.measure(request(model="other"))["calibration_ratio"] == 1


def test_serializing_provider_blocks_does_not_mutate_live_objects():
    block = tool_block("a", {"text": "中文"})
    block.extra = {"signature": "synthetic-signature"}
    assert plain(block)["extra"] == {"signature": "synthetic-signature"}
    assert block.type == "tool_use"


@pytest.mark.parametrize("kwargs", [{"context_policy": "typo"}, {"context_window_tokens": -1},
                                    {"context_safety_tokens": -1}, {"tool_output_bytes": 100}])
def test_invalid_context_settings_are_rejected(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)
