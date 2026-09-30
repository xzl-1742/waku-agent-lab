"""Snapshot published checkpoints and visible facts without changing the agent.

Only the live evaluation supplies these observers. Every snapshot is copied
before a restart or later revision can replace it; judging happens afterwards.
"""

import json

from evals.context.evidence import conversation, persisted, receipt, valid_receipts
from evals.context.fixtures import expand

MEMORY_LIMIT = 200


def expectations(case, messages, *, memory=False):
    """Use only observed user text; a future correction cannot label old history."""
    texts = {m["text"] for m in messages if m["session_id"] == "primary-project"}
    turns = [s for s in expand(case) if s["op"] == "turn"]
    introduced = turns[case["position"]]["message"] in texts
    changed = case["family"] in ("corrections", "forgetting") and turns[case["position"] + 2]["message"] in texts
    required, forbidden = [], []
    if changed:
        forbidden = [case["old"]]
    if introduced and case["family"] != "tools":
        value = case["current"] if changed else case["old"]
        if not (changed and case["family"] == "forgetting"):
            required = [f'{case["subject"]}: {value}']
    # Only explicit remember/correct instructions require durable fact recall.
    if memory and case["family"] not in ("corrections", "forgetting", "retrieval"):
        required = []
    return {"required": required, "forbidden": forbidden}


def sources(app, session=None, through=None):
    clause, params = "role='user'", []
    if session is not None:
        clause += " AND session_id=? AND id<=?"
        params = [session, through]
    rows = app.conn.execute(f"SELECT id,session_id,content_json FROM session_messages WHERE {clause} ORDER BY id", params)
    result = []
    for row in rows:
        content = json.loads(row["content_json"])
        if isinstance(content, str):  # tool observations are not user assertions
            result.append({"source_id": row["id"], "session_id": row["session_id"], "text": content})
    return result


def receipts(app, session, through):
    rows = app.conn.execute(
        "SELECT * FROM tool_executions WHERE state='complete' "
        "AND session_id=? AND turn_id IN (SELECT turn_id FROM session_messages WHERE session_id=? AND id<=?) ORDER BY rowid",
        (session, session, through))
    return [persisted(app, r) for r in rows]


class ProbeCapture:
    def __init__(self, case):
        self.case = case
        self.events, self.checkpoints, self.errors = [], [], []
        self.memory = None
        self.inputs = []
        self.persisted = None
        self.executions = []
        self.retrieval_events = []

    def user_message(self, session, text):
        self.inputs.append({"source_id": len(self.inputs) + 1, "session_id": session, "text": text})

    def observer(self, app):
        def observe(kind, event):
            if kind in ("gate", "retrieval", "retrieval_detail"):
                # Only synthetic live evaluations attach this observer. Copy
                # decisions and delivered IDs before the next turn changes them.
                self.retrieval_events.append({"turn": len(self.inputs), "session_id": app.session.session_id,
                                              "kind": kind, "event": json.loads(json.dumps(event))})
                return
            if kind == "tool":
                try:
                    if event.get("result_id"):
                        row = app.conn.execute("SELECT * FROM tool_executions WHERE result_id=? AND session_id=?",
                            (event["result_id"], app.session.session_id)).fetchone()
                        if row is None:
                            raise ValueError("Completed tool event has no persisted execution")
                        item = persisted(app, row)
                    else:
                        item = receipt(event["tool"], event["args"], event["output"], app.session.session_id)
                    self.executions.append(item)
                except Exception as exc:
                    self.errors.append({"kind": "tool", "error_type": type(exc).__name__})
                return
            if kind != "compaction_completed":
                return
            identity = {k: event[k] for k in ("session_id", "revision", "covered_through")}
            self.events.append(identity)
            try:
                row = app.conn.execute("SELECT * FROM session_checkpoints WHERE session_id=? AND revision=?",
                                       (identity["session_id"], identity["revision"])).fetchone()
                if row is None or row["covered_through"] != identity["covered_through"]:
                    raise ValueError("Published checkpoint could not be captured")
                evidence = sources(app, identity["session_id"], identity["covered_through"])
                # The update receipt names the replaced ID. Snapshot the actual
                # replacement now, before a later correction changes this mapping.
                active = json.loads(row["metadata_json"]).get("active_turn")
                versions = [{"source_id": turn.last_id, **dict(fact)}
                            for turn in app.checkpoints.sources(identity["session_id"], active_turn=active)
                            if turn.last_id <= identity["covered_through"]
                            for fact in app.checkpoints.corrections(turn.turn_id, identity["session_id"])]
                self.checkpoints.append({**identity, "snapshot": json.loads(row["summary_json"]),
                    "evidence": evidence, **expectations(self.case, evidence),
                    "memory_versions": versions,
                    "conversation": conversation(app, identity["session_id"], identity["covered_through"]),
                    "receipts": receipts(app, identity["session_id"], identity["covered_through"])})
            except Exception as exc:
                # A failed eval observer must not turn a successful publication
                # into a runtime compaction failure or trigger another attempt.
                self.errors.append({**identity, "error_type": type(exc).__name__})
        return observe

    def finish(self, app, actions, replies=None):
        try:
            self.persisted = [dict(r) for r in app.conn.execute(
                "SELECT session_id,revision,covered_through FROM session_checkpoints ORDER BY rowid")]
            facts = app.memory.facts.list(limit=MEMORY_LIMIT + 1)
            if len(facts) > MEMORY_LIMIT:
                raise ValueError("Final memory snapshot exceeds the evaluation bound")
            # Window/legacy deliberately has no canonical message records.
            # The evaluator's input log provides equal evidence for all arms.
            evidence = list(self.inputs)
            self.memory = {"snapshot": [{k: r.get(k) for k in ("id", "subject", "content", "source", "scope", "scope_id")}
                                        for r in facts], "evidence": evidence, "dialogue": list(replies or []),
                           **expectations(self.case, evidence, memory=True), "receipts": list(self.executions)}
        except Exception as exc:
            self.errors.append({"kind": "memory", "error_type": type(exc).__name__})

    def report(self):
        return {"schema_version": 2, "events": self.events, "checkpoints": self.checkpoints,
                "retrieval_events": self.retrieval_events,
                "persisted": self.persisted, "memory": self.memory, "capture_errors": self.errors, "checks": []}


def checks(probes):
    """Deterministic expected check inventory; graders never choose coverage."""
    result = []
    for index, item in enumerate(probes["checkpoints"]):
        result.append((f"checkpoint/{index}", "checkpoint", item, item["snapshot"], None))
    memory = probes["memory"]
    if memory is not None:
        for index, fact in enumerate(memory["snapshot"]):
            result.append((f"memory/support/{index}", "memory_support", memory, fact, fact.get("source")))
        for index, fact in enumerate(memory["required"]):
            result.append((f"memory/recall/{index}", "memory_recall", {**memory, "required": [fact]}, memory["snapshot"], None))
    return result


def judge_payload(kind, evidence, snapshot):
    tasks = {
        "checkpoint": "Assess this task checkpoint: it must preserve ALL required constraints, avoid forbidden current claims, and only claim completed actions with receipts.",
        "memory_support": "Assess this stored fact: every factual claim must be supported by user evidence or actual receipts. It must not retain a forgotten or superseded value as current.",
        "memory_recall": "Assess these stored facts: they must express ALL required facts with the correct subject. An empty store fails when a fact is required.",
    }
    if kind == "checkpoint":
        tasks[kind] += " Conversation source IDs refer to the full covered transcript. A receipt source_id identifies the user turn, not every assistant/result message. Metadata is not a separate factual claim. Dialogue can prove an answer was given but cannot prove an external action succeeded."
        tasks[kind] += " memory_versions is a database snapshot at checkpoint publication: supersedes identifies the old ID named by an update receipt, while id identifies its current replacement. Assess value support from user evidence and receipts."
    if kind in ("memory_support", "memory_recall"):
        tasks[kind] += " The reply is an actual database snapshot. Assess only subject/content; IDs, source and scope are metadata, not additional factual claims or requests to prove storage. Explicit 'remember X' user text supports X."
        def project(fact):
            return {k: fact[k] for k in ("subject", "content")}
        snapshot = project(snapshot) if kind == "memory_support" else [project(f) for f in snapshot]
    return {"task": tasks[kind], "evidence": {"user_messages": evidence["evidence"],
            "conversation": evidence.get("conversation", []), "dialogue": evidence.get("dialogue", []),
            "memory_versions": evidence.get("memory_versions", []),
            "required": evidence["required"] if kind != "memory_support" else [],
            "forbidden": evidence["forbidden"]}, "reply": json.dumps(snapshot, ensure_ascii=False),
            "receipts": evidence["receipts"]}


def grade_probes(probes, client, model):
    from evals.context.quality import blind, grade

    for key, kind, evidence, snapshot, source in checks(probes):
        item = {"id": key, **judge_payload(kind, evidence, snapshot)}
        blinded, _ = blind([item], 20260929)
        row = {"id": key, "kind": kind, "source": source, "input": blinded[0], "verdict": None, "error_type": None}
        try:
            row["verdict"] = grade(client, model, blinded[0])
        except Exception as exc:
            row["error_type"] = type(exc).__name__
        probes["checks"].append(row)
    return probes


def probe_status(probes, case=None):
    from evals.context.quality import validate

    try:
        if not isinstance(probes, dict) or probes.get("schema_version") != 2 or probes.get("capture_errors") or probes.get("memory") is None:
            return "incomplete"
        if not valid_receipts(probes["memory"]["receipts"]):
            return "incomplete"
        if any(not valid_receipts(p["receipts"], session=p["session_id"], through=p["covered_through"]) for p in probes["checkpoints"]):
            return "incomplete"
        identities = [tuple(r[k] for k in ("session_id", "revision", "covered_through")) for r in probes["events"]]
        captured = [tuple(r[k] for k in ("session_id", "revision", "covered_through")) for r in probes["checkpoints"]]
        persisted = [tuple(r[k] for k in ("session_id", "revision", "covered_through")) for r in probes["persisted"]]
        if identities != captured or identities != persisted or len(identities) != len(set(identities)):
            return "incomplete"
        if case is not None:
            session, observed = "primary-project", []
            for step in expand(case):
                if step["op"] in ("restart", "switch"):
                    session = step["session"]
                else:
                    observed.append((session, step["message"]))
            if [(m["session_id"], m["text"]) for m in probes["memory"]["evidence"]] != observed:
                return "incomplete"
            for item, memory in [(p, False) for p in probes["checkpoints"]] + [(probes["memory"], True)]:
                wanted = expectations(case, item["evidence"], memory=memory)
                if any(item[k] != wanted[k] for k in ("required", "forbidden")):
                    return "incomplete"
        expected = [(key, kind, source) for key, kind, _, _, source in checks(probes)]
        actual = [(r["id"], r["kind"], r["source"]) for r in probes["checks"]]
        if expected != actual or any(r.get("error_type") for r in probes["checks"]):
            return "incomplete"
        verdicts = [validate(json.dumps(r["verdict"])) for r in probes["checks"]]
        if any(not v["task_success"] or v["stale_assertion"] or v["unsupported_assertion"] for v in verdicts):
            return "failed"
        return "complete"
    except (KeyError, TypeError, ValueError):
        return "incomplete"


def metrics(probes):
    complete = probe_status(probes) != "incomplete"
    def ratio(kind, source=None):
        rows = [r for r in (probes or {}).get("checks", []) if r["kind"] == kind and (source is None or r["source"] == source)]
        passed = sum(bool(r.get("verdict", {}) and r["verdict"].get("task_success")
                          and not r["verdict"].get("stale_assertion") and not r["verdict"].get("unsupported_assertion")) for r in rows)
        return {"passed": passed, "total": len(rows), "rate": passed / len(rows) if complete and rows else None}
    return {"status": probe_status(probes), "checkpoint_retention": ratio("checkpoint"),
            "memory_supportedness": ratio("memory_support"), "required_fact_recall": ratio("memory_recall"),
            "consolidated_fact_supportedness": ratio("memory_support", "consolidation")}
