"""Compare existing and selective retrieval with scripted gates and real stores.

python -m evals.retrieval.runner --split all --output eval-results/retrieval-v4.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from evals.context.measurement import RecordingClient, source_snapshot

FIXTURES = Path(__file__).with_name("cases.json")
LABELS = {"legacy": "V4-retrieval-control", "selective": "V4-retrieval-candidate"}


def load_cases():
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    cases = data["cases"]
    if data["schema_version"] != 1 or len(cases) != 24 or len({c["id"] for c in cases}) != 24:
        raise ValueError("Expected the frozen 24-case retrieval bank")
    counts = Counter((c["category"], c["split"]) for c in cases)
    if set(counts.values()) != {1, 2} or len(counts) != 16:
        raise ValueError("Expected eight stratified categories")
    for case in cases:
        keys = {r["key"] for r in case["rows"]}
        if not set(case["gold"] + case["forbidden"]) <= keys or set(case["gold"]) & set(case["forbidden"]):
            raise ValueError("Inconsistent evidence labels")
    return data


def run_case(case, home, policy, k=4, budget_tokens=1024):
    from evals.helpers import ScriptedClient, make_waku, response, text_block
    from waku.memory.retrieval import tokens

    if not os.environ.get("WAKU_EVAL_ROOT") or not home.resolve().is_relative_to(Path(os.environ["WAKU_EVAL_ROOT"]).resolve()):
        raise RuntimeError("Retrieval evaluations require the offline isolation bootstrap")
    gate = {"retrieve": case["gate_retrieve"], "query": case["query"] if case["gate_retrieve"] else "", "reason": "scripted"}
    if policy == "selective":
        gate["mode"] = "search"
    client = RecordingClient(ScriptedClient([response([text_block(json.dumps(gate))])]), synthetic=True)
    app = make_waku(home, client=client, provider="anthropic", model="scripted-answer", small_model="scripted-small",
                    memory_policy="lifecycle", retrieval_policy=policy, context_policy="budget", retrieval_top_k=k,
                    retrieval_tokens=budget_tokens, project_id=case["project_id"], history_turns=12,
                    semantic_store="sqlite", episodic_store="sqlite", consolidate_every=10000,
                    experimental=False, gh_tool=False)
    app.session.start_new(case["session_id"])
    app.session.history = case["history"]
    mapping, data = {}, {}
    events, errors = [], []
    def observe(kind, value):
        events.append({"kind": kind, **value})
    def keys(ids):
        return [mapping[tuple(i)] for i in ids]
    def identify(rendered):
        return [key for key, row in data.items() if row["content"] in rendered]
    try:
        for row in case["rows"]:
            if row["kind"] == "fact":
                rid = app.conn.execute("INSERT INTO facts(subject,content,source,scope,scope_id,validity,created_at) VALUES(?,?,?,?,?,?,?)",
                                       (row["subject"], row["content"], row["source"], row["scope"], row["scope_id"], row["validity"], "2026-01-01")).lastrowid
            else:
                rid = app.conn.execute("INSERT INTO episodes(summary,happened_at,scope,scope_id,validity) VALUES(?,?,?,?,?)",
                                       (row["content"], "2026-01-01", row["scope"], row["scope_id"], row["validity"])).lastrowid
            mapping[(row["kind"], rid)], data[row["key"]] = row["key"], row
        app.conn.commit()
        if policy == "selective":
            search_ids = keys([(r["kind"], r["id"]) for r in app.memory.retrieval.rows(case["query"])])
        else:
            search_ids = identify("\n".join(app.memory.facts.search(case["query"], k) + app.memory.episodes.search(case["query"], 3)))
        rendered = app.memory.gated_retrieve(case["message"], dialogue=case["history"], checkpoint=case["checkpoint"], notify=observe)
        if policy == "selective":
            payload = json.loads(rendered) if rendered else {"entries": []}
            initial_ids = keys([(r["kind"], r["id"]) for r in payload["entries"]])
        else:
            payload, initial_ids = None, identify(rendered)
        delivered_ids = list(initial_ids)
        recovery = ""
        if case["recovery_query"]:
            recovery = app.tools.execute("manage_memory", {"action": "search", "query": case["recovery_query"]}, notify=observe)
            recovered = (keys([(r["kind"], r["id"]) for r in json.loads(recovery)["entries"]])
                         if policy == "selective" else identify(recovery))
            delivered_ids = list(dict.fromkeys(initial_ids + recovered))
        gold = set(case["gold"])
        recall = lambda ids: len(set(ids) & gold) / len(gold) if gold else None
        # Relevant spans are entire fixture records. This is an explicit byte
        # share proxy: metadata and serialization overhead remain in denominator.
        if payload is not None:
            relevant_bytes = sum(len(r["text"].encode("utf-8")) for r in payload["entries"]
                                 if mapping[(r["kind"], r["id"])] in gold)
        else:
            relevant_bytes = sum(len(data[key]["content"].encode("utf-8")) for key in initial_ids if key in gold)
        estimated = tokens(payload) if payload is not None and rendered else tokens(rendered) if rendered else 0
        result = {"id": case["id"], "category": case["category"], "split": case["split"], "policy": LABELS[policy],
                  "search_recall_at_k": recall(search_ids), "delivered_recall_at_k": recall(initial_ids),
                  "post_recovery_recall_at_k": recall(delivered_ids),
                  "gate_false_negative": bool(case["requires_memory"] and not gate["retrieve"]),
                  "gate_status": next((e.get("status", e.get("decision")) for e in events if e["kind"] == "gate"), None),
                  "initial_ids": initial_ids, "search_ids": search_ids, "delivered_ids": delivered_ids,
                  "relevant_estimated_token_share": relevant_bytes / estimated if estimated else None,
                  "estimated_retrieval_tokens": estimated, "budget_exceeded": estimated > budget_tokens,
                  "recovery_attempts": int(bool(case["recovery_query"])),
                  "new_recovery_ids": [i for i in delivered_ids if i not in initial_ids],
                  "forbidden_evidence": sorted(set(delivered_ids) & set(case["forbidden"])),
                  "ranking_check": (search_ids[:len(case["order"])] == case["order"] if "order" in case else None),
                  "stale_assertions": None, "unsupported_assertions": None,
                  "events": events, "calls": client.calls, "errors": errors}
        critical = result["forbidden_evidence"] or (policy == "selective" and (
            result["budget_exceeded"] or result["ranking_check"] is False))
        result["status"] = "failed" if critical else "complete"
        return result
    except Exception as exc:
        return {"id": case["id"], "policy": LABELS[policy], "status": "failed", "errors": [repr(exc)]}
    finally:
        app.close()
        app.conn.close()


def report(cases, root, k=4, budget_tokens=1024):
    from waku.memory.retrieval_gate import GATE_PROMPT
    from waku.memory.selective_gate import PROMPT

    results = [run_case(c, root / policy / c["id"], policy, k, budget_tokens) for policy in LABELS for c in cases]
    summaries = {}
    for label in LABELS.values():
        subset = [r for r in results if r["policy"] == label]
        def mean(name, subset=subset):
            values = [r[name] for r in subset if r.get(name) is not None]
            return sum(values) / len(values) if values else None
        summaries[label] = {"cases": len(subset), "complete": sum(r["status"] == "complete" for r in subset),
                            **{field: mean(field) for field in ("search_recall_at_k", "delivered_recall_at_k",
                                                               "post_recovery_recall_at_k", "relevant_estimated_token_share")},
                            "scripted_gate_false_negatives": sum(r.get("gate_false_negative", False) for r in subset),
                            "recovery_attempts": sum(r.get("recovery_attempts", 0) for r in subset),
                            "forbidden_evidence_cases": sum(bool(r.get("forbidden_evidence")) for r in subset),
                            "budget_exceeded_cases": sum(r.get("budget_exceeded", False) for r in subset)}
    return {"schema_version": 1, "source": source_snapshot(), "fixture_sha256": hashlib.sha256(FIXTURES.read_bytes()).hexdigest(),
            "settings": {"k": k, "retrieval_tokens": budget_tokens, "memory_policy": "lifecycle", "context_policy": "budget"},
            "prompts": {"legacy": GATE_PROMPT, "selective": PROMPT}, "summary": summaries, "cases": results,
            "status": "failed" if any(r["status"] == "failed" for r in results if r["policy"] == LABELS["selective"]) else "complete",
            "quality_status": "incomplete", "stale_assertions": None, "unsupported_assertions": None,
            "input_tokens": None, "output_tokens": None, "cost_usd": None,
            "limits": ["Gate decisions and resolved queries are scripted; gate comprehension is unmeasured.",
                       "Recall measures evidence availability; semantic paraphrase misses remain visible.",
                       "Relevant token share uses fixture spans and serialized UTF-8 bytes, not provider tokens.",
                       "Critical failures cover forbidden evidence, candidate budgets and declared ranking order; no minimum average recall is hidden.",
                       "No answer model or judge runs; stale/unsupported assertion rates remain unmeasured."]}


def main():
    from evals.isolation import install

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("development", "reserved", "all"), default="development")
    parser.add_argument("--output", type=Path, default=Path("eval-results/retrieval-v4.json"))
    args = parser.parse_args()
    scratch = install()
    bank = load_cases()
    cases = [c for c in bank["cases"] if args.split == "all" or c["split"] == args.split]
    with tempfile.TemporaryDirectory(prefix="retrieval-", dir=scratch) as root:
        result = report(cases, Path(root), bank["k"], bank["budget_tokens"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "summary": result["summary"]}, indent=2))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
