"""The paid pilot reserves spend before transport and stops on unknown usage."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from evals.context.deepseek_pilot import MODEL, Budget, PilotStopped, factory, run


def test_pilot_requires_explicit_execution_before_configuration():
    with pytest.raises(ValueError, match="explicit"):
        run(SimpleNamespace(live=False))


def test_full_context_reservation_blocks_a_request_before_sending():
    budget = Budget("2", 100)
    with pytest.raises(PilotStopped, match="budget"):
        budget.reserve(MODEL, 8192)
    assert budget.calls == 0 and budget.upper == 0


def test_peak_spend_ignores_cache_discounts_and_releases_unused_reservation():
    budget = Budget("5", 1)
    reservation = budget.reserve(MODEL, 8192)
    assert reservation.amount == Decimal("2.162688")
    budget.settle(reservation, SimpleNamespace(prompt_tokens=1000, completion_tokens=100))
    assert budget.upper == Decimal("0.0028")
    with pytest.raises(PilotStopped, match="allowance"):
        budget.reserve(MODEL, 1)
    assert budget.calls == 1


@pytest.mark.parametrize("usage", [None, SimpleNamespace(prompt_tokens=100),
                                  SimpleNamespace(prompt_tokens=-1, completion_tokens=1)])
def test_missing_usage_retains_reservation_and_stops(usage):
    budget = Budget("5", 10)
    reservation = budget.reserve(MODEL, 8192)
    with pytest.raises(PilotStopped):
        budget.settle(reservation, usage)
    assert budget.upper == reservation.amount
    with pytest.raises(PilotStopped):
        budget.reserve(MODEL, 1)


@pytest.mark.parametrize("model,tokens", [("deepseek-v4-pro", 10), (MODEL, 8193), (MODEL, 0)])
def test_changed_model_or_output_limit_never_reaches_transport(model, tokens):
    with pytest.raises(PilotStopped):
        Budget("5", 10).reserve(model, tokens)


def test_transport_disables_thinking_retries_and_redirects_and_stops_after_error(tmp_path, monkeypatch):
    import openai

    from evals.context.quality import RUBRIC

    observed = []
    def create(**request):
        observed.append(request)
        raise RuntimeError("synthetic transport failure")
    def sdk(**settings):
        assert settings["base_url"] == "https://api.deepseek.com"
        assert settings["max_retries"] == 0 and settings["timeout"] == 90
        assert not settings["http_client"].follow_redirects
        settings["http_client"].close()
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: None)
    monkeypatch.setattr(openai, "OpenAI", sdk)
    budget = Budget("5", 10)
    make, close = factory("synthetic", budget, tmp_path)
    client = make(None)
    for _ in range(2):
        with pytest.raises(PilotStopped):
            client.messages.create(model=MODEL, messages=[{"role": "user", "content": RUBRIC + "fixture"}], max_tokens=10)
    assert len(observed) == 1
    assert observed[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert observed[0]["response_format"] == {"type": "json_object"}
    assert observed[0]["max_tokens"] == 10 and "max_completion_tokens" not in observed[0]
    assert budget.calls == 1 and budget.upper > 2
    import json
    error = json.loads((tmp_path / "deepseek-errors.jsonl").read_text())
    assert error["error_type"] == "RuntimeError" and error["request_number"] == 1
    assert "synthetic transport failure" not in json.dumps(error)
    close()


def test_durable_budget_keeps_unknown_reservation_across_batches_and_settles_once(tmp_path):
    path = tmp_path / "budget.jsonl"
    first = Budget("5", 10, path)
    pending = first.reserve(MODEL, 8192)
    first.close()  # Represents an interruption before response usage was available.
    second = Budget("5", 10, path)
    assert second.upper == pending.amount and len(second.pending) == 1
    measured = second.reserve(MODEL, 100)
    second.settle(measured, SimpleNamespace(prompt_tokens=1000, completion_tokens=100,
                                           prompt_cache_hit_tokens=600, prompt_cache_miss_tokens=400))
    assert second.upper == pending.amount + Decimal("0.001624")
    with pytest.raises(PilotStopped, match="settled"):
        second.settle(measured, SimpleNamespace(prompt_tokens=1000, completion_tokens=100))
    second.close()
    third = Budget("5", 10, path)
    assert third.upper == pending.amount + Decimal("0.001624")
    third.close()


def test_campaign_rejects_concurrent_writer_and_increased_allowance(tmp_path):
    path = tmp_path / "budget.jsonl"
    first = Budget("5", 10, path)
    with pytest.raises(OSError):
        Budget("5", 10, path)
    first.close()
    with pytest.raises(ValueError, match="allowance"):
        Budget("10", 10, path)


def test_explicit_allowance_increase_keeps_spend_and_unknown_reservations(tmp_path):
    import json

    path = tmp_path / "budget.jsonl"
    first = Budget("5", 10, path)
    pending = first.reserve(MODEL, 8192)
    measured = first.reserve(MODEL, 100)
    first.settle(measured, SimpleNamespace(prompt_tokens=1000, completion_tokens=100))
    before = first.upper
    first.close()
    original = path.read_bytes()
    raised = Budget("8", 10, path, allow_increase=True)
    assert raised.limit == 8 and raised.upper == before and raised.initial_upper == before
    assert list(raised.pending) == [pending.id]
    raised.close()
    assert path.read_bytes().startswith(original)
    assert json.loads(path.read_text().splitlines()[-1]) == {"kind": "allowance", "previous_cny": "5", "limit_cny": "8"}
    restored = Budget("8", 10, path)
    assert restored.upper == before and len(restored.pending) == 1
    restored.close()
    with pytest.raises(ValueError, match="allowance"):
        Budget("5", 10, path, allow_increase=True)


def test_corrupt_campaign_ledger_fails_closed(tmp_path):
    path = tmp_path / "budget.jsonl"
    budget = Budget("5", 10, path)
    budget.reserve(MODEL, 100)
    budget.close()
    with path.open("a") as handle:
        handle.write('{"kind":')
    with pytest.raises(ValueError):
        Budget("5", 10, path)


@pytest.mark.parametrize("usage", [
    SimpleNamespace(prompt_tokens=1000, completion_tokens=1, prompt_cache_hit_tokens=900, prompt_cache_miss_tokens=200),
    SimpleNamespace(prompt_tokens=1000, completion_tokens=101),
])
def test_inconsistent_usage_retains_the_full_durable_reservation(tmp_path, usage):
    path = tmp_path / "budget.jsonl"
    budget = Budget("5", 10, path)
    reserved = budget.reserve(MODEL, 100)
    with pytest.raises(PilotStopped):
        budget.settle(reserved, usage)
    budget.close()
    restored = Budget("5", 10, path)
    assert restored.upper == reserved.amount
    restored.close()
