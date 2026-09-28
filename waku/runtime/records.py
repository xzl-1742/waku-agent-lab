"""Original messages and tool receipts, independent of disposable prompt text."""

from __future__ import annotations

import hashlib
import json
import re
from uuid import uuid4

from waku.runtime.context import TurnStopped, encode

_RESULT_ID = re.compile(r"[0-9a-f]{32}\Z")
_OUTCOME_KEY = re.compile(r"\b(status|error|failed|warning|receipt|saved|created|path|destination|synced|sent|id)\b", re.IGNORECASE)
_JSON_KEYS = {"status", "error", "errors", "warning", "warnings", "id", "receipt", "path",
              "destination", "synced", "sent", "success", "url", "result_id"}


def prefix(text, size):
    return text.encode("utf-8")[:size].decode("utf-8", errors="ignore")


def suffix(text, size):
    return text.encode("utf-8")[-size:].decode("utf-8", errors="ignore") if size else ""


def outcome_fields(output, budget=800):
    """Quoted tool claims, not an inferred guarantee that a side effect succeeded."""
    fields = {}
    try:
        data = json.loads(output)
    except (ValueError, RecursionError):
        data = None
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in _JSON_KEYS:
                fields[key] = prefix(encode(value), 160)
    else:
        # Include relevant lines even at the tail of a large log.
        lines = [prefix(line, 160) for line in output.splitlines() if _OUTCOME_KEY.search(line)]
        fields = {"reported_lines": lines[-4:]} if lines else {}
    while fields and len(encode(fields).encode("utf-8")) > budget:
        fields.pop(next(iter(fields)))
    return fields


def reduce_output(output, result_id, cap):
    if len(output.encode("utf-8")) <= cap:
        return output
    record = {"execution": "complete", "action_success": "unverified",
              "result_id": result_id, "bytes": len(output.encode("utf-8")),
              "truncated": True, "reported_fields": outcome_fields(output, cap // 4),
              "read": "manage_memory(action='read_result', result_id=..., offset=0, limit=...)",
              "excerpt": ""}
    room = cap // 2
    while True:
        record["excerpt"] = prefix(output, room // 2) + "\n[omitted]\n" + suffix(output, room // 2)
        rendered = encode(record)
        if len(rendered.encode("utf-8")) <= cap:
            return rendered
        room //= 2
        if room == 0:
            record["reported_fields"] = {}


class ExecutionStore:
    def __init__(self, conn, home, output_cap=4096):
        self.conn, self.home, self.output_cap = conn, home, output_cap

    def path(self, result_id):
        if not isinstance(result_id, str) or not _RESULT_ID.fullmatch(result_id):
            raise ValueError("Invalid result ID")
        home = self.home.resolve()
        root = self.home / "results"
        if root.is_symlink() or (hasattr(root, "is_junction") and root.is_junction()):
            raise ValueError("Result directory cannot be a link")
        if not root.resolve().is_relative_to(home):
            raise ValueError("Result directory escapes agent home")
        path = root / f"{result_id}.txt"
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Result path escapes result directory")
        return path

    def read(self, session_id, result_id, offset=0, limit=1024):
        if type(offset) is not int or type(limit) is not int or offset < 0 or limit < 1:
            raise ValueError("offset and limit must be non-negative/positive integer byte counts")
        path = self.path(result_id)
        row = self.conn.execute(
            "SELECT state, result_bytes FROM tool_executions WHERE result_id=? AND session_id=?",
            (result_id, session_id),
        ).fetchone()
        if row is None:
            raise ValueError("Result not found in the active session")
        if row["state"] != "complete":
            raise ValueError("Execution outcome is unknown; do not repeat the action automatically")
        if offset > row["result_bytes"]:
            raise ValueError("offset exceeds result size")
        size = min(limit, max(4, self.output_cap // 8))
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(size)
            # Finish the last UTF-8 character; next_offset always starts a character.
            while True:
                try:
                    content = data.decode("utf-8")
                    break
                except UnicodeDecodeError as exc:
                    if exc.reason != "unexpected end of data":
                        raise ValueError("offset must start at a UTF-8 character boundary") from exc
                    byte = handle.read(1)
                    if not byte:
                        raise ValueError("Invalid UTF-8 result") from exc
                    data += byte
        return encode({"result_id": result_id, "offset": offset, "next_offset": offset + len(data),
                       "eof": offset + len(data) == row["result_bytes"], "content": content})

    def turn(self, session_id, source):
        return TurnRecord(self, session_id, source)


class TurnRecord:
    def __init__(self, store, session_id, source):
        self.store, self.session_id, self.source = store, session_id, source
        self.turn_id, self.position, self.tool_calls = uuid4().hex, 0, []

    def message(self, role, content):
        try:
            self.store.conn.execute(
                "INSERT INTO session_messages (session_id,turn_id,position,role,content_json,source) "
                "VALUES (?,?,?,?,?,?)",
                (self.session_id, self.turn_id, self.position, role, encode(content), self.source),
            )
            self.store.conn.commit()
            self.position += 1
        except Exception as exc:
            raise TurnStopped("Could not record this turn. Completed tools will not be retried.") from exc

    def begin(self, call_id, tool, args):
        result_id = uuid4().hex
        try:
            self.store.conn.execute(
                "INSERT INTO tool_executions "
                "(result_id,session_id,turn_id,call_id,tool,args_json,state) VALUES (?,?,?,?,?,?,'pending')",
                (result_id, self.session_id, self.turn_id, call_id, tool, encode(args)),
            )
            self.store.conn.commit()
            return result_id
        except Exception as exc:
            raise TurnStopped("Could not record a pending tool call; the tool was not executed.") from exc

    def finish(self, result_id, output):
        try:
            data = output.encode("utf-8")
            path = self.store.path(result_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Never overwrite a result or follow an existing result file.
            with path.open("xb") as handle:
                handle.write(data)
                handle.flush()
            self.store.conn.execute(
                "UPDATE tool_executions SET state='complete',outcome_json=?,result_bytes=?,"
                "result_sha256=?,completed_at=datetime('now') WHERE result_id=?",
                (encode({"action_success": "unverified", "reported_fields": outcome_fields(output)}),
                 len(data), hashlib.sha256(data).hexdigest(), result_id),
            )
            self.store.conn.commit()
        except Exception as exc:
            raise TurnStopped(
                "The tool ran but its result could not be committed. Its outcome is unknown; "
                "check the original destination before repeating the action."
            ) from exc
        return reduce_output(output, result_id, self.store.output_cap)
