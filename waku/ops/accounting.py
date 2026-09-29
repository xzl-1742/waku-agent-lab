"""One usage row per SDK invocation, independent of observer fan-out.

The wrapper sits below memory and budget guards. Explicit adapter retries are
separate calls; hidden SDK HTTP retries are outside this accounting boundary.
"""

import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from types import SimpleNamespace

from waku.runtime.context import fingerprint

_stage = ContextVar("model_stage", default="unclassified")
_scope = ContextVar("model_scope", default="runtime")
call_context = ContextVar("call_context", default=None)
_meter = ContextVar("active_usage_meter", default=None)


@contextmanager
def model_stage(stage, scope="runtime"):
    first, second = _stage.set(stage), _scope.set(scope)
    try:
        yield
    finally:
        _scope.reset(second)
        _stage.reset(first)


def count(value):
    return value if type(value) is int and value >= 0 else None


def usage_fields(usage):
    """Keep missing, partial and measured-zero usage distinct."""
    if usage is None or getattr(usage, "measured", True) is False:
        return {"in": None, "out": None, "usage_source": "unmeasured",
                "cache_read_input_tokens": None, "cache_creation_input_tokens": None,
                "cache_included_in_input": None}
    openai = hasattr(usage, "prompt_tokens")
    incoming = count(getattr(usage, "prompt_tokens" if openai else "input_tokens", None))
    outgoing = count(getattr(usage, "completion_tokens" if openai else "output_tokens", None))
    cached = (getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None) if openai
              else getattr(usage, "cache_read_input_tokens", None))
    return {"in": incoming, "out": outgoing,
            "usage_source": "provider" if incoming is not None and outgoing is not None else "partial",
            "cache_read_input_tokens": count(cached),
            "cache_creation_input_tokens": count(getattr(usage, "cache_creation_input_tokens", None)),
            "cache_included_in_input": openai or bool(getattr(usage, "cache_included_in_input", False))}


def normalized_openai_usage(usage):
    fields = usage_fields(usage)
    return SimpleNamespace(input_tokens=fields["in"] or 0, output_tokens=fields["out"] or 0,
                           measured=fields["usage_source"] == "provider",
                           cache_read_input_tokens=fields["cache_read_input_tokens"],
                           cache_creation_input_tokens=fields["cache_creation_input_tokens"],
                           cache_included_in_input=True)


class Attempt:
    def __init__(self, meter, request):
        self.meter, self.request = meter, request
        self.started, self.done = time.perf_counter(), False
        self.usage = None
        self.context = dict(call_context.get() or {})
        self.stage, self.scope = _stage.get(), _scope.get()

    def finish(self, status, error=None):
        if self.done:
            return
        self.done = True
        self.meter["attempts"] += 1
        stage = self.stage
        self.meter["record"]({"schema_version": 2, "call_id": uuid.uuid4().hex,
            "operation_id": self.meter["operation_id"], **self.context,
            "provider": self.meter["provider"], "model": self.request.get("model", ""),
            "stage": stage, "scope": self.scope, "kind": "loop" if stage == "answer" else stage,
            "status": status, "error_type": type(error).__name__ if error else None,
            "duration_seconds": time.perf_counter() - self.started,
            "request_sha256": fingerprint(self.request), **usage_fields(self.usage)})


class UsageIterator:
    """Own a raw OpenAI stream, including partial usage on failure or close."""
    def __init__(self, stream, attempt):
        self.stream, self.attempt = stream, attempt

    def __iter__(self):
        try:
            for chunk in self.stream:
                if getattr(chunk, "usage", None) is not None:
                    self.attempt.usage = chunk.usage
                yield chunk
        except BaseException as exc:
            self.attempt.finish("cancelled" if isinstance(exc, GeneratorExit) else "failed", exc)
            raise
        else:
            self.attempt.finish("complete")
        finally:
            self.close()

    def close(self):
        self.attempt.finish("cancelled")
        close = getattr(self.stream, "close", None)
        if close:
            close()


def sdk_call(fn, request):
    """Called by the OpenAI adapter before interpreting a provider response."""
    meter = _meter.get()
    if meter is None:
        return fn(**request)
    attempt = Attempt(meter, request)
    try:
        result = fn(**request)
    except BaseException as exc:
        attempt.finish("failed", exc)
        raise
    if request.get("stream"):
        return UsageIterator(result, attempt)
    attempt.usage = getattr(result, "usage", None)
    attempt.finish("complete")
    return result


class UsageClient:
    def __init__(self, client, settings, record):
        self.client, self.settings, self.record = client, settings, record
        self.messages = SimpleNamespace(create=self.create)
        if hasattr(client.messages, "stream"):
            self.messages.stream = self.stream

    def __getattr__(self, name):
        return getattr(self.client, name)

    @contextmanager
    def operation(self, request):
        meter = {"attempts": 0, "operation_id": uuid.uuid4().hex,
                 "provider": self.settings.provider, "record": self.record}
        token = _meter.set(meter)
        try:
            yield meter, Attempt(meter, request)
        finally:
            _meter.reset(token)

    def create(self, **request):
        with self.operation(request) as (meter, attempt):
            try:
                result = self.client.messages.create(**request)
                attempt.usage = getattr(result, "usage", None)
            except BaseException as exc:
                if not meter["attempts"] and not getattr(self.client, "records_sdk_calls", False):
                    attempt.finish("failed", exc)
                raise
            if not meter["attempts"] and not getattr(self.client, "records_sdk_calls", False):
                attempt.finish("complete")
            return result

    @contextmanager
    def stream(self, **request):
        with self.operation(request) as (meter, attempt):
            final = None
            stream = None
            status, error = "cancelled", None
            try:
                with self.client.messages.stream(**request) as stream:
                    class Stream:
                        @property
                        def text_stream(self):
                            return stream.text_stream

                        def get_final_message(self):
                            nonlocal final, status
                            if final is None:
                                final = stream.get_final_message()
                                attempt.usage = getattr(final, "usage", None)
                                status = "complete"
                            return final
                    yield Stream()
            except BaseException as exc:
                status, error = "failed", exc
                raise
            finally:
                if not meter["attempts"] and not getattr(self.client, "records_sdk_calls", False):
                    if attempt.usage is None and stream is not None:
                        try:
                            attempt.usage = getattr(stream.current_message_snapshot, "usage", None)
                        except (AttributeError, RuntimeError):
                            pass
                    attempt.finish(status, error)


def account_client(client, settings, record=None):
    if record is None:
        from waku.ops.tracing import Tracer

        record = Tracer(settings).record_call
    if isinstance(client, UsageClient):
        client.record = record
        return client
    return UsageClient(client, settings, record)
