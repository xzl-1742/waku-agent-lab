"""Durable pre-dispatch reservations shared by sequential Flash pilot batches."""

import json
import os
import threading
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

MODEL = "deepseek-flash"
CONTEXT = 1048576
MILLION = Decimal(1000000)


class PilotStopped(RuntimeError):
    pass


@dataclass(frozen=True)
class Reservation:
    id: str
    max_tokens: int

    @property
    def amount(self):
        return (Decimal(CONTEXT) * 2 + self.max_tokens * 8) / MILLION


class Budget:
    def __init__(self, limit, max_calls, ledger=None):
        self.limit = Decimal(str(limit))
        if not self.limit.is_finite() or self.limit <= 0 or type(max_calls) is not int or max_calls < 1:
            raise ValueError("Budget and call allowance must be positive")
        self.max_calls, self.calls = max_calls, 0
        self.upper = Decimal(0)
        self.pending = {}
        self.stopped = False
        self.lock = threading.Lock()
        self.handle = self.owner = None
        if ledger is not None:
            ledger.parent.mkdir(parents=True, exist_ok=True)
            self.owner = ledger.with_suffix(ledger.suffix + ".lock").open("a+b")
            try:
                self.owner.seek(0, 2)
                if not self.owner.tell():
                    self.owner.write(b"0")
                    self.owner.flush()
                self.owner.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.owner.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.handle = ledger.open("a+", encoding="utf-8")
                self.handle.seek(0)
                lines = self.handle.readlines()
                header = {"schema_version": 1, "model": MODEL, "limit_cny": str(self.limit),
                          "pricing_checked_at": "2026-09-29", "input_peak": "2", "cached_peak": "0.04", "output_peak": "8"}
                if lines:
                    if json.loads(lines[0]) != header:
                        raise ValueError("Campaign allowance or pricing differs from its ledger")
                    for line in lines[1:]:
                        self._apply(json.loads(line))
                else:
                    self._append(header)
            except Exception:
                self.close()
                raise
        self.initial_upper = self.upper

    def _append(self, row):
        if self.handle:
            self.handle.write(json.dumps(row) + "\n")
            self.handle.flush()
            os.fsync(self.handle.fileno())

    def _apply(self, row):
        identity = row["id"]
        if row["kind"] == "reserve":
            if identity in self.pending or type(row["max_tokens"]) is not int or not 1 <= row["max_tokens"] <= 8192:
                raise ValueError("Invalid reservation in budget ledger")
            reservation = Reservation(identity, row["max_tokens"])
            if self.upper + reservation.amount > self.limit:
                raise ValueError("Budget ledger exceeds its allowance")
            self.pending[identity] = reservation
            self.upper += reservation.amount
        elif row["kind"] == "settle":
            reservation = self.pending[identity]
            charged = self.charge(row["input"], row["output"], row["cached"], reservation)
            self.upper += charged - reservation.amount
            del self.pending[identity]
        else:
            raise ValueError("Unknown budget journal event")

    @staticmethod
    def charge(incoming, outgoing, cached, reservation):
        if any(type(v) is not int or v < 0 for v in (incoming, outgoing, cached)):
            raise PilotStopped("Provider usage missing; reservation retained")
        if incoming > CONTEXT or outgoing > reservation.max_tokens or cached > incoming:
            raise PilotStopped("Provider usage exceeded reserved limits")
        return ((incoming - cached) * 2 + Decimal(cached) * Decimal("0.04") + outgoing * 8) / MILLION

    def reserve(self, model, max_tokens):
        if model != MODEL or type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
            raise PilotStopped("Pilot model or output limit changed")
        reservation = Reservation(uuid4().hex, max_tokens)
        with self.lock:
            if self.stopped or self.calls >= self.max_calls or self.upper + reservation.amount > self.limit:
                self.stopped = True
                raise PilotStopped("Pilot budget or call allowance exhausted")
            row = {"kind": "reserve", "id": reservation.id, "max_tokens": max_tokens}
            self._append(row)  # Durable before transport; a crash retains this full reserve.
            self._apply(row)
            self.calls += 1
        return reservation

    def settle(self, reservation, usage):
        incoming = getattr(usage, "prompt_tokens", None)
        outgoing = getattr(usage, "completion_tokens", None)
        hit = getattr(usage, "prompt_cache_hit_tokens", None)
        miss = getattr(usage, "prompt_cache_miss_tokens", None)
        try:
            cached = 0
            if hit is not None or miss is not None:
                if any(type(v) is not int or v < 0 for v in (hit, miss)) or hit + miss != incoming:
                    raise PilotStopped("Inconsistent cache usage; reservation retained")
                cached = hit
            self.charge(incoming, outgoing, cached, reservation)
            with self.lock:
                if self.pending.get(reservation.id) != reservation:
                    raise PilotStopped("Reservation was already settled or is unknown")
                row = {"kind": "settle", "id": reservation.id, "input": incoming, "output": outgoing, "cached": cached}
                self._append(row)
                self._apply(row)
        except Exception:
            self.stopped = True
            raise

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None
        if self.owner:
            self.owner.close()  # OS releases the exclusive writer lock, including on process exit.
            self.owner = None
