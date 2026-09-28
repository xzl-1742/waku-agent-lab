"""Wiring — builds one Waku from its parts. Gateways call `respond()`.

This file is the assembly diagram in code: config → db → tools → memory →
session → loop. If you want to understand the repo in one place, start here.
"""

from __future__ import annotations

from waku.config import Settings, load_settings
from waku.db import connect
from waku.loop.agent import LoopResult, Observer, run_loop
from waku.loop.models import get_client
from waku.ops.tracing import Tracer, compose
from waku.runtime.context import ContextBudget, TurnStopped, guard_client
from waku.runtime.records import ExecutionStore
from waku.runtime.session import Session
from waku.tools import build_registry


class Waku:
    def __init__(self, settings: Settings | None = None, client=None, conn=None):
        # `client` and `conn` are injectable: evals swap in a scripted model,
        # the dashboard injects a cross-thread connection. Same seam either way.
        self.settings = settings or load_settings()
        self.settings.ensure_home()
        self.conn = conn or connect(self.settings.home)
        self.client = client or get_client(self.settings)
        self.budget = ContextBudget.from_settings(self.settings)
        self.client = guard_client(self.client, self.budget)
        if self.budget is None:
            # An explicit opt-out propagates into run_loop for baseline A.
            self.client.context_budget = None

        # Memory first: the memory-management tools need it.
        from waku.memory import Memory

        self.memory = Memory(self.conn, self.settings, self.client)
        self.session = Session(self.settings, memory=self.memory)
        self.records = ExecutionStore(self.conn, self.settings.home, self.settings.tool_output_bytes)
        reader = (lambda result_id, offset, limit: self.records.read(
            self.session.session_id, result_id, offset, limit)) if self.budget else None
        self.tools = build_registry(self.conn, self.settings, self.memory, result_reader=reader)
        self.mcp_bridge = getattr(self.tools, "mcp_bridge", None)
        self._turn_record = None
        self.tracer = Tracer(self.settings)

    def close(self) -> None:
        """Release external resources (MCP subprocesses). Called when the
        dashboard rebuilds the agent after a settings change."""
        if self.mcp_bridge is not None:
            self.mcp_bridge.close()

    def respond(self, user_message: str, observer: Observer | None = None,
                source: str = "cli", stream: bool = False) -> LoopResult:
        """One full turn: assemble working memory → run the loop → persist.
        `source` tags which gateway the message arrived through (cli / voice /
        telegram / dashboard), so the unified chat can show its origin.
        `stream=True` streams the reply text token by token to the observer.
        Everything that happens is both shown (observer) and recorded (tracer)."""
        # capture the gate + graph decisions as they flow by, so we can persist
        # them with the turn (the reopened-thread telemetry the dashboard shows)
        import time
        captured: dict = {}

        def _capture(kind, ev):
            if kind == "gate":
                captured["gate"] = {"decision": ev.get("decision"), "reason": ev.get("reason")}
            if kind == "route":
                captured["graph_route"] = {"target": ev.get("target"), "reason": ev.get("reason")}
            if kind == "triage":
                captured["triage_reason"] = ev.get("reason")
            if kind == "graph_end":
                captured["graph_path"] = ev.get("path")
        notify = compose(observer, self.tracer.event, _capture)
        t0 = time.perf_counter()
        if self.budget:
            self.client.notify = notify
        self._turn_record = self.records.turn(self.session.session_id, source) if self.budget else None

        with self.tracer.turn(user_message):
            # The graph front door is optional and can NEVER make Waku worse:
            # flag off → this is exactly the old code path; flag on → the triage
            # graph decides quick vs full, and any failure anywhere falls open
            # to the plain loop below (same fail-open rule as the retrieval gate).
            result, stopped = None, False
            try:
                if self._turn_record:
                    self._turn_record.message("user", user_message)
                if self.settings.graph_workflows:
                    try:
                        result = self._respond_via_graph(user_message, notify, stream)
                    except TurnStopped:
                        raise
                    except Exception as exc:
                        notify("graph_end", {"workflow": "triage", "ms": 0, "steps": 0,
                                             "path": [], "error": repr(exc)})
                        # Once a tool started, falling back can duplicate its effect.
                        if self._turn_record and self.conn.execute(
                            "SELECT 1 FROM tool_executions WHERE turn_id=? LIMIT 1",
                            (self._turn_record.turn_id,),
                        ).fetchone():
                            raise TurnStopped("Workflow stopped after tool execution; no action was repeated.") from exc
                if result is None:
                    result = self._run_full_turn(user_message, notify, stream)
                if self._turn_record and self._turn_record.position == 1:
                    self._turn_record.message("assistant", result.reply)
            except TurnStopped as exc:
                stopped = True
                result = LoopResult(reply=str(exc), tool_calls=(self._turn_record.tool_calls
                                                               if self._turn_record else []))
                notify("context_error", {"error": str(exc)})

            quick = captured.get("graph_route", {}).get("target") == "quick_reply"

            def _status(out: str) -> str:
                low = (out or "").lower()
                return "error" if ("failed" in low or "timed out" in low
                                   or low.startswith("error")) else "ok"
            meta = {
                "gate": captured.get("gate"),
                "graph": ({"workflow": "triage",
                           "route": "quick" if quick else "full",
                           "reason": captured.get("triage_reason", ""),
                           "path": captured.get("graph_path")}
                          if "graph_route" in captured else None),
                "iterations": result.iterations,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "tools": [{"tool": c["tool"], "status": _status(c["output"])}
                          for c in result.tool_calls],
                # which brain answered this turn — so a reopened thread (or a
                # thread you switched models mid-way) shows it per card. A quick
                # graph turn was answered by the small model; say so honestly.
                "model": self.settings.small_model if quick else self.settings.model,
                "provider": self.settings.provider,
            }
            self.session.add_exchange(user_message, result.reply, tool_calls=result.tool_calls,
                                      source=source, meta=meta)
            if self.memory is not None and not stopped:
                self.memory.maybe_consolidate(notify=notify)
                self.memory.export_markdown()   # keep MEMORY.md in sync

        self.tracer.end_turn(result.reply, result.iterations)
        return result

    def _run_full_turn(self, user_message: str, notify, stream: bool) -> LoopResult:
        """The classic turn: assemble working memory, run THE loop. Extracted
        verbatim so the graph's full_agent node calls the SAME code as the
        flag-off default — loop-as-a-node can never drift from loop-as-default."""
        system = self.session.build_system(user_message, notify=notify)
        # Working memory is a bounded window: only the last N turns (2 rows
        # each) enter the prompt, so context/cost/latency stay flat no matter
        # how long the conversation runs. Older turns live in state.db and
        # come back via the retrieval gate + episodic memory when relevant.
        window = self.settings.history_turns * 2
        history = self.session.history[-window:] if window else []
        messages = history + [{"role": "user", "content": user_message}]

        return run_loop(
            client=self.client,
            model=self.settings.model,
            system=system,
            messages=messages,
            tools=self.tools,
            max_iterations=self.settings.max_iterations,
            max_tokens=self.settings.max_tokens,
            observer=notify,
            stream=stream,
            budget=self.budget,
            records=self._turn_record,
        )

    def _respond_via_graph(self, user_message: str, notify, stream: bool) -> LoopResult | None:
        """One turn through the triage graph workflow. Returns None whenever
        the graph didn't produce an answer — respond() then falls open to the
        plain loop, so this path can only ever ADD speed, never lose a reply."""
        from waku.graph import run_graph
        from waku.graph.workflows.triage import (
            QUICK_REPLY_PROMPT,
            build_triage_graph,
            classify_message,
            todays_events,
        )

        def quick_reply(state: dict) -> str:
            prompt = QUICK_REPLY_PROMPT.format(calendar=state.get("calendar", ""),
                                               message=state["message"])
            response = self.client.messages.create(
                model=self.settings.small_model, max_tokens=600,
                messages=[{"role": "user", "content": prompt}])
            return "".join(b.text for b in response.content if b.type == "text")

        graph = build_triage_graph(
            classify_fn=lambda m: classify_message(self.client, self.settings.small_model, m),
            calendar_fn=lambda: todays_events(self.settings.home),
            quick_fn=quick_reply,
            # the full path is the SAME method the flag-off default runs; the
            # engine's tagged notifier stamps its inner events with node=
            full_fn=lambda state: self._run_full_turn(
                state["message"], state.get("_notify", notify), stream),
        )
        state = run_graph(graph, {"message": user_message}, observer=notify)
        if isinstance(state.get("result"), LoopResult):
            return state["result"]
        if state.get("reply"):
            return LoopResult(reply=state["reply"], tool_calls=[], iterations=1)
        if self._turn_record and self.conn.execute(
            "SELECT 1 FROM tool_executions WHERE turn_id=? LIMIT 1",
            (self._turn_record.turn_id,),
        ).fetchone():
            raise TurnStopped("Workflow stopped after tool execution; no action was repeated.")
        return None  # graph produced nothing → caller falls open to the loop
