"""Apply durable suppression before model dispatch, even after feature disablement."""

from contextlib import contextmanager
from types import SimpleNamespace

from waku.memory.locking import memory_lock
from waku.runtime.context import TurnStopped, plain


class MemoryClient:
    def __init__(self, client, policy):
        self.client, self.policy = client, policy
        self.context_budget = getattr(client, "context_budget", None)
        self.messages = SimpleNamespace(create=self.create)
        if hasattr(client.messages, "stream"):
            self.messages.stream = self.stream

    @property
    def notify(self):
        return getattr(self.client, "notify", None)

    @notify.setter
    def notify(self, value):
        self.client.notify = value

    def prepare(self, request):
        if not self.policy.generation:
            return request
        request = dict(request)
        for key in ("system", "messages"):
            if key in request:
                if key == "system" and isinstance(request[key], str):
                    request[key] = "\n".join(self.policy.clean_text(line) for line in request[key].split("\n"))
                else:
                    request[key] = self.policy.clean_value(plain(request[key]))
        return request

    def check(self, generation):
        if self.policy.generation != generation:
            raise TurnStopped("Memory changed during this model call; its stale response was discarded.")

    def create(self, **request):
        with memory_lock(self.policy.settings.home):
            generation = self.policy.generation
            response = self.client.messages.create(**self.prepare(request))
            self.check(generation)
            return response

    @contextmanager
    def stream(self, **request):
        with memory_lock(self.policy.settings.home):
            generation = self.policy.generation
            with self.client.messages.stream(**self.prepare(request)) as stream:
                owner = self

                class CheckedStream:
                    @property
                    def text_stream(self):
                        for delta in stream.text_stream:
                            owner.check(generation)
                            yield delta

                    def get_final_message(self):
                        response = stream.get_final_message()
                        owner.check(generation)
                        return response

                yield CheckedStream()
