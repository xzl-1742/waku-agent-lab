"""Authoritative fixture-tool outcomes for judges, never model arguments alone."""

import hashlib
import json

TOOLS = {"save_note", "manage_memory", "record_action", "read_fixture"}
MAX_BYTES = 131072


def outcome(tool, args, output):
    if tool == "save_note":
        return output == f"Saved to memory under '{args.get('subject')}': {args.get('content')}"
    if tool == "manage_memory" and args.get("action", "").lower() in ("update", "delete"):
        action = args["action"].lower()
        kind = args.get("kind", "fact")
        return output == f"{'Updated' if action == 'update' else 'Deleted'} {kind} #{args.get('id', 0)}."
    if output.startswith(("Error", "No fact with id", "No episode with id", "Not executed:")):
        return False
    return None  # A returned observation alone does not prove an arbitrary side effect.


def receipt(tool, args, output, session, *, result_id=None, turn_id=None, source_id=None):
    if tool not in TOOLS or not isinstance(args, dict) or not isinstance(output, str):
        raise ValueError("Unknown evaluation tool evidence")
    data = output.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise ValueError("Tool evidence exceeds the capture bound")
    # This lossless encoding avoids repeatedly sending a 64 KiB fixture log.
    projected = {"encoding": "repeat", "text": "x", "count": len(output)} if tool == "read_fixture" and output and set(output) == {"x"} else output
    return {"tool": tool, "args": json.loads(json.dumps(args)), "output": projected,
            "execution": "complete", "action_success": outcome(tool, args, output),
            "session_id": session, "turn_id": turn_id, "result_id": result_id,
            "source_id": source_id, "output_bytes": len(data), "output_sha256": hashlib.sha256(data).hexdigest()}


def persisted(app, row):
    if row["state"] != "complete":
        raise ValueError("Pending execution is not evidence of completion")
    if row["result_bytes"] > MAX_BYTES:
        raise ValueError("Persisted result exceeds the capture bound")
    # Eval-only access to synthetic originals; the agent's suppression-aware read
    # API remains unchanged. Historical receipts never assert current validity.
    with app.records.path(row["result_id"]).open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) != row["result_bytes"] or hashlib.sha256(data).hexdigest() != row["result_sha256"]:
        raise ValueError("Persisted tool evidence failed integrity checking")
    first = app.conn.execute("SELECT MIN(id) FROM session_messages WHERE session_id=? AND turn_id=? AND role='user'",
                             (row["session_id"], row["turn_id"])).fetchone()[0]
    return receipt(row["tool"], json.loads(row["args_json"]), data.decode("utf-8"), row["session_id"],
                   result_id=row["result_id"], turn_id=row["turn_id"], source_id=first)


def valid_receipts(rows, *, session=None, through=None):
    if not isinstance(rows, list):
        return False
    for row in rows:
        try:
            value = row["output"]
            if isinstance(value, dict):
                if set(value) != {"encoding", "text", "count"} or value["encoding"] != "repeat" or value["text"] != "x":
                    return False
                if type(value["count"]) is not int or not 0 < value["count"] <= MAX_BYTES:
                    return False
                value = "x" * value["count"]
            expected = receipt(row["tool"], row["args"], value, row["session_id"],
                result_id=row["result_id"], turn_id=row["turn_id"], source_id=row["source_id"])
            if row != expected or not isinstance(row["session_id"], str):
                return False
            if session is not None and (row["session_id"] != session or type(row["source_id"]) is not int or not 0 < row["source_id"] <= through):
                return False
        except (KeyError, TypeError, ValueError):
            return False
    return True


def conversation(app, session, through):
    """Preserve covered message roles and IDs for claims about prior dialogue."""
    rows = app.conn.execute("SELECT id,role,content_json FROM session_messages WHERE session_id=? AND id<=? ORDER BY id",
                            (session, through))
    result = []
    for row in rows:
        content = json.loads(row["content_json"])
        if isinstance(content, list):
            for block in content:
                text = block.get("content")
                if block.get("type") == "tool_result" and isinstance(text, str) and text and set(text) == {"x"}:
                    block["content"] = {"encoding": "repeat", "text": "x", "count": len(text)}
        result.append({"source_id": row["id"], "role": row["role"], "content": content})
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 1048576:
        raise ValueError("Conversation evidence exceeds the evaluation bound")
    return result
