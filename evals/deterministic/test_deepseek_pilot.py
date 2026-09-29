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
    assert reservation == Decimal("2.162688")
    budget.settle(reservation, SimpleNamespace(prompt_tokens=1000, completion_tokens=100, prompt_cache_hit_tokens=1000))
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
    assert budget.upper == reservation
    with pytest.raises(PilotStopped):
        budget.reserve(MODEL, 1)


@pytest.mark.parametrize("model,tokens", [("deepseek-v4-pro", 10), (MODEL, 8193), (MODEL, 0)])
def test_changed_model_or_output_limit_never_reaches_transport(model, tokens):
    with pytest.raises(PilotStopped):
        Budget("5", 10).reserve(model, tokens)


def test_transport_disables_thinking_retries_and_redirects_and_stops_after_error(tmp_path, monkeypatch):
    import openai

    observed = []
    def create(**request):
        observed.append(request)
        raise RuntimeError("synthetic transport failure")
    def sdk(**settings):
        assert settings["base_url"] == "https://api.deepseek.com"
        assert settings["max_retries"] == 0 and settings["timeout"] == 30
        assert not settings["http_client"].follow_redirects
        settings["http_client"].close()
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: None)
    monkeypatch.setattr(openai, "OpenAI", sdk)
    budget = Budget("5", 10)
    make, close = factory("synthetic", budget, tmp_path)
    client = make(None)
    for _ in range(2):
        with pytest.raises(PilotStopped):
            client.messages.create(model=MODEL, messages=[{"role": "user", "content": "fixture"}], max_tokens=10)
    assert len(observed) == 1
    assert observed[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert observed[0]["max_tokens"] == 10 and "max_completion_tokens" not in observed[0]
    assert budget.calls == 1 and budget.upper > 2
    close()
