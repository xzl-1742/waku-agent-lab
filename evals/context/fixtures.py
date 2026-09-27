"""Expand frozen scenario data into explicit turns, tools and lifecycle steps."""

import json
from collections import Counter
from pathlib import Path

FIXTURES = Path(__file__).with_name("scenarios.json")
FAMILIES = {"constraints", "tools", "corrections", "forgetting", "retrieval", "isolation"}


def load_cases(path=FIXTURES):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported scenario schema")
    cases = data["cases"]
    required = {"id", "family", "split", "turns", "position", "output_kib",
                "subject", "old", "current", "question"}
    for case in cases:
        if set(case) != required or case["family"] not in FAMILIES:
            raise ValueError("Unknown scenario fields or family")
        if case["split"] not in ("development", "reserved"):
            raise ValueError("Unknown fixture split")
        if case["turns"] not in (8, 32, 96) or case["output_kib"] not in (1, 16, 64):
            raise ValueError("Unsupported scenario size")
        if not 0 <= case["position"] < case["turns"] - 4:
            raise ValueError("Invalid evidence position")
        if any(not isinstance(case[k], str) or not case[k]
               for k in ("id", "subject", "old", "current", "question")):
            raise ValueError("Scenario strings must be non-empty")
    counts = Counter((c["family"], c["split"]) for c in cases)
    expected = {(f, s): n for f in FAMILIES for s, n in (("development", 4), ("reserved", 2))}
    if counts != expected or len({c["id"] for c in cases}) != 36:
        raise ValueError("Expected 36 unique, stratified cases (24 development, 12 reserved)")
    return cases


def tool(name, **args):
    return {"name": name, "args": args}


def expand(case):
    """The script specifies fake model output; outcome checks inspect real state."""
    family, count, position = case["family"], case["turns"], case["position"]
    subject, old, current = case["subject"], case["old"], case["current"]
    turns = [{"op": "turn", "message": f"Unrelated arithmetic step {i}: what is 2+2?",
              "reply": "4", "tools": [], "query": ""} for i in range(count)]
    turns[position].update(message=f"For {subject}, keep this constraint: {old}", reply="Recorded.")
    if family in ("corrections", "forgetting", "retrieval"):
        turns[position]["message"] = f"Remember this about {subject}: {old}"
        turns[position]["tools"] = [tool("save_note", subject=subject, content=old)]
    if family == "tools":
        turns[position]["message"] = f"Perform {subject} once, then keep the receipt."
        turns[position]["tools"] = [tool("record_action", receipt=old)]
    # Every family includes a large, irrelevant tool observation.
    turns[position + 1].update(message="Read the synthetic log for this task.", reply="Log read.",
                               tools=[tool("read_fixture")])
    if family in ("corrections", "forgetting"):
        action = "update" if family == "corrections" else "delete"
        turns[position + 2].update(
            message=(f"Correction: {current}. Replace the old value." if action == "update"
                     else f"Forget the fact about {subject}."),
            reply="Memory changed.", tools=[tool("manage_memory", action="search", query=subject),
                                           tool("manage_memory", action=action, id=1,
                                                **({"content": current} if action == "update" else {}))],
        )
    turns[-1].update(message=case["question"], reply=current,
                     query=subject if family in ("corrections", "forgetting", "retrieval") else "")
    if family == "isolation":
        # The transcript is separated by session IDs in the same persistent home.
        turns[-2].update(message="OTHER_SESSION_SENTINEL: project Z uses port 9999.", reply="Noted.")
        turns.insert(count - 2, {"op": "switch", "session": "other-project"})
        turns.insert(len(turns) - 1, {"op": "restart", "session": "primary-project"})
    elif family == "tools":
        turns.insert(len(turns) - 1, {"op": "restart", "session": "primary-project"})
    return turns
