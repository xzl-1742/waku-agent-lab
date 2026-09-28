"""Dependency-free request budgets. Estimates are not provider token counts."""

from __future__ import annotations

import hashlib
import json
import math
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import RLock
from types import SimpleNamespace

ESTIMATOR = "utf8-json-bytes-v1"
FALLBACK_CAPACITY = 32768


class TurnStopped(RuntimeError):
    """A terminal failure: callers must not retry the turn or its side effects."""


class ContextOverflow(TurnStopped):
    pass


def plain(value):
    """Serialize a snapshot without replacing live provider content blocks."""
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, SimpleNamespace):
        return plain(vars(value))
    return value


def encode(value):
    return json.dumps(plain(value), ensure_ascii=False, separators=(",", ":"))


def estimate_request(request):
    # One token per UTF-8 byte is deliberately conservative for text/code/CJK.
    # Count schemas, system, messages and any extra request fields; add framing.
    return len(encode(request).encode("utf-8")) + 256 + 32 * len(request.get("messages", []))


def fingerprint(request):
    return hashlib.sha256(encode(request).encode("utf-8")).hexdigest()


def is_user_request(message):
    if message.get("role") != "user":
        return False
    content = plain(message.get("content"))
    return not (isinstance(content, list) and any(b.get("type") == "tool_result" for b in content))


def validate_pairs(messages):
    """Every call batch is immediately followed by its whole result batch."""
    pending = []
    for message in messages:
        blocks = plain(message.get("content"))
        blocks = blocks if isinstance(blocks, list) else []
        calls = [b["id"] for b in blocks if b.get("type") == "tool_use"]
        results = [b["tool_use_id"] for b in blocks if b.get("type") == "tool_result"]
        if pending:
            if message.get("role") != "user" or sorted(results) != sorted(pending):
                raise ContextOverflow("Context error: a tool call is missing its paired result batch.")
            pending = []
        elif results:
            raise ContextOverflow("Context error: tool results have no preceding tool calls.")
        if calls:
            if message.get("role") != "assistant" or len(set(calls)) != len(calls):
                raise ContextOverflow("Context error: invalid tool-call identifiers.")
            pending = calls
    if pending:
        raise ContextOverflow("Context error: tool results are still pending.")


@dataclass
class ContextBudget:
    capacity: int = FALLBACK_CAPACITY
    small_capacity: int = FALLBACK_CAPACITY
    main_model: str = ""
    small_model: str = ""
    margin: int = 1024
    capacity_source: str = "conservative_fallback"
    small_capacity_source: str = "conservative_fallback"
    ratios: dict = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False)

    @classmethod
    def from_settings(cls, settings):
        if settings.context_policy == "window":
            return None
        return cls(
            capacity=settings.context_window_tokens or FALLBACK_CAPACITY,
            small_capacity=settings.small_context_window_tokens or FALLBACK_CAPACITY,
            main_model=settings.model, small_model=settings.small_model,
            margin=settings.context_safety_tokens,
            capacity_source="configured" if settings.context_window_tokens else "conservative_fallback",
            small_capacity_source=("configured" if settings.small_context_window_tokens
                                   else "conservative_fallback"),
        )

    def measure(self, request):
        model = request.get("model", "")
        choices = []
        if model == self.main_model:
            choices.append((self.capacity, self.capacity_source))
        if model == self.small_model:
            choices.append((self.small_capacity, self.small_capacity_source))
        capacity, source = min(choices) if choices else (FALLBACK_CAPACITY, "conservative_fallback")
        reserve = request.get("max_tokens", 0)
        with self._lock:
            ratio = self.ratios.get(model, 1.0)
        estimated = math.ceil(estimate_request(request) * ratio)
        return {"estimator": ESTIMATOR, "estimated_input_tokens": estimated,
                "capacity_tokens": capacity, "output_reserve_tokens": reserve,
                "safety_tokens": self.margin, "input_budget_tokens": capacity - reserve - self.margin,
                "capacity_source": source,
                "calibration_ratio": ratio, "model": model}

    def check(self, request):
        info = self.measure(request)
        if info["estimated_input_tokens"] > info["input_budget_tokens"]:
            raise ContextOverflow(
                f"Context budget exceeded: estimated input {info['estimated_input_tokens']} tokens; "
                f"available {info['input_budget_tokens']} after reserving output and safety margin. "
                "Shorten the current request or configure a verified context capacity. "
                "Completed tools have not been retried."
            )
        return info

    def fit(self, request):
        """Drop old complete exchanges only; the active turn cannot be dropped."""
        messages = request["messages"]
        validate_pairs(messages)
        removed = 0
        while self.measure(request)["estimated_input_tokens"] > self.measure(request)["input_budget_tokens"]:
            starts = [i for i, message in enumerate(messages) if is_user_request(message)]
            if len(starts) < 2:
                break
            end = starts[1]
            del messages[:end]
            removed += end
        info = self.check(request)
        return {**info, "dropped_messages": removed}

    def observe(self, request, response):
        usage = getattr(response, "usage", None)
        # Normalized adapters explicitly identify missing usage. Fake zeroes do
        # not calibrate anything. Cached Anthropic inputs also consume context.
        if getattr(usage, "measured", True) is False:
            return None
        tokens = getattr(usage, "input_tokens", None)
        if tokens is None:
            return None
        tokens += (getattr(usage, "cache_read_input_tokens", 0) or 0)
        tokens += (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        if tokens <= 0:
            return None
        base = estimate_request(request)
        with self._lock:
            model = request.get("model", "")
            self.ratios[model] = max(self.ratios.get(model, 1.0), tokens / base)
        return {"observed_input_tokens": tokens, "request_sha256": fingerprint(request),
                "usage_source": "provider", "estimator": ESTIMATOR}


class BudgetedClient:
    """Guard every call made through this client, including helper/graph calls."""

    def __init__(self, client, budget):
        self.client, self.context_budget = client, budget
        self.notify = lambda kind, event: None
        self.messages = SimpleNamespace(create=self.create)
        if hasattr(client.messages, "stream"):
            self.messages.stream = self.stream

    def create(self, **kwargs):
        self._check(kwargs)
        response = self.client.messages.create(**kwargs)
        observed = self.context_budget.observe(kwargs, response)
        if observed:
            self.notify("context_usage", observed)
        return response

    @contextmanager
    def stream(self, **kwargs):
        self._check(kwargs)
        with self.client.messages.stream(**kwargs) as stream:
            owner = self

            class ObservedStream:
                @property
                def text_stream(self):
                    return stream.text_stream

                def get_final_message(self):
                    response = stream.get_final_message()
                    observed = owner.context_budget.observe(kwargs, response)
                    if observed:
                        owner.notify("context_usage", observed)
                    return response

            yield ObservedStream()

    def _check(self, request):
        info = self.context_budget.measure(request)
        try:
            self.context_budget.check(request)
        except ContextOverflow:
            self.notify("context", {**info, "stage": "rejected"})
            raise
        self.notify("context", {**info, "stage": "dispatch"})


def guard_client(client, budget):
    if budget is None or isinstance(client, BudgetedClient):
        return client
    return BudgetedClient(client, budget)
