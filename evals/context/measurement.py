"""Observe real call boundaries and record reproducible, secret-free metadata."""

import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

from evals.context.fixtures import FIXTURES

ROOT = Path(__file__).resolve().parents[2]


def request_stage(kwargs):
    from waku.memory.consolidation import SUMMARIZER_PROMPT
    from waku.memory.retrieval_gate import GATE_PROMPT

    if "system" in kwargs:
        return "answer"
    content = str(kwargs.get("messages", [{}])[0].get("content", ""))
    for stage, prompt in (("gate", GATE_PROMPT), ("consolidation", SUMMARIZER_PROMPT)):
        if content.startswith(prompt.split("\n\n")[0]):
            return stage
    return "unknown"


def digest(value) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         default=lambda obj: vars(obj)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RecordingClient:
    """Counts harness client calls, not hidden SDK retries or HTTP requests."""

    def __init__(self, client, *, synthetic=False, clock=time.perf_counter):
        self.client, self.synthetic, self.clock = client, synthetic, clock
        self.calls = []
        self.messages = SimpleNamespace(create=self.create)
        self.last_main_input = ""

    def create(self, **kwargs):
        from waku.runtime.context import estimate_request, validate_pairs

        stage = request_stage(kwargs)
        validate_pairs(kwargs.get("messages", []))
        if stage == "answer":
            self.last_main_input = str(kwargs)
        record = {"stage": stage, "model": kwargs.get("model"),
                  "estimated_input_tokens": estimate_request(kwargs),
                  "max_tokens": kwargs.get("max_tokens"),
                  "tool_schema_sha256": digest(kwargs.get("tools", [])),
                  "pairing_valid": True,
                  "request_sha256": digest(kwargs), "status": "failed",
                  "input_tokens": None, "output_tokens": None,
                  "usage_source": "synthetic" if self.synthetic else "unmeasured"}
        started = self.clock()
        try:
            result = self.client.messages.create(**kwargs)
            record["status"] = "complete"
            if not self.synthetic:
                usage = getattr(result, "usage", None)
                for key in ("input_tokens", "output_tokens"):
                    record[key] = getattr(usage, key, None)
                if all(record[k] is not None for k in ("input_tokens", "output_tokens")):
                    record["usage_source"] = "client_reported"
            return result
        finally:
            record["duration_seconds"] = self.clock() - started
            self.calls.append(record)


def record_tools(registry, records, clock=time.perf_counter):
    execute = registry.execute

    def measured(name, args, notify=None):
        started = clock()
        record = {"tool": name, "status": "failed"}
        try:
            output = execute(name, args, notify=notify)
            record["status"] = "failed" if output.startswith("Error") else "complete"
            record["output_bytes"] = len(output.encode("utf-8"))
            return output
        finally:
            record["duration_seconds"] = clock() - started
            records.append(record)

    registry.execute = measured


def source_snapshot(root=ROOT):
    """Hash only code and bundled skills; never inspect env, homes or attachments."""
    paths = [root / "pyproject.toml", root / "uv.lock"]
    for folder, suffixes in (("waku", {".py", ".sql"}),
                             ("evals", {".py", ".json", ".jsonl"}),
                             ("skills", {".md"})):
        paths.extend(p for p in (root / folder).rglob("*") if p.is_file() and p.suffix in suffixes)
    manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(paths) if p.is_file()}
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                                  capture_output=True, text=True, check=False)
        commit = revision.stdout.strip() if revision.returncode == 0 else None
    except OSError:
        commit = None
    return {"commit": commit, "manifest_sha256": digest(manifest), "files": manifest}


def metadata(configuration="A", capacity=32768):
    from waku.memory.consolidation import SUMMARIZER_PROMPT
    from waku.memory.retrieval_gate import GATE_PROMPT
    from waku.runtime.session import DEFAULT_SOUL, RESULT_READ_RULE

    prompts = {"soul": DEFAULT_SOUL, "gate": GATE_PROMPT, "consolidation": SUMMARIZER_PROMPT}
    if configuration == "B":
        prompts["result_read_rule"] = RESULT_READ_RULE
    references = json.loads(FIXTURES.with_name("references.json").read_text(encoding="utf-8"))
    return {
        "schema_version": 2, "configuration": configuration, "runner": "scripted-offline-v1",
        "python": platform.python_version(), "platform": platform.system(),
        "models": {"answer": "scripted-answer", "gate": "scripted-small",
                   "consolidation": "scripted-small", "judge": None},
        "settings": {"history_turns": 12, "consolidate_every": 6, "retrieval_top_k": 4,
                     "max_iterations": 10, "max_tokens": 8192, "stream": False,
                     "semantic_store": "sqlite", "episodic_store": "sqlite",
                     "context_policy": "window" if configuration == "A" else "budget",
                     "context_window_tokens": capacity, "small_context_window_tokens": capacity,
                     "context_safety_tokens": 1024, "tool_output_bytes": 4096},
        "clock": "2026-01-15T12:00:00+00:00", "trial": 1,
        "prompts": {k: {"text": v, "sha256": digest(v)} for k, v in prompts.items()},
        "fixtures_sha256": hashlib.sha256(FIXTURES.read_text(encoding="utf-8").encode()).hexdigest(),
        "references": references, "references_sha256": digest(references),
        "source": source_snapshot(),
    }
