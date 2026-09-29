"""Serialize lifecycle turns and mutations for one home across processes."""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from functools import wraps

from waku.runtime.context import TurnStopped

_locks = {}
_registry_lock = threading.Lock()
_local = threading.local()


@contextmanager
def memory_lock(home):
    path = str(home.resolve())
    with _registry_lock:
        lock = _locks.setdefault(path, threading.RLock())
    with lock:
        held = getattr(_local, "held", set())
        if path in held:
            yield
            return
        home.mkdir(parents=True, exist_ok=True)
        with (home / "memory.lock").open("a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            deadline = time.monotonic() + 30
            while True:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise TurnStopped("Memory is busy in another process; this turn did not run.") from exc
                    time.sleep(0.05)
            _local.held = held | {path}
            try:
                yield
            finally:
                _local.held = held
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def serialized(fn):
    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        with memory_lock(self.settings.home):
            return fn(self, *args, **kwargs)
    return wrapped
