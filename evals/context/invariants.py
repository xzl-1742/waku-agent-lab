"""Deterministic checks for literal disclosures in the frozen synthetic bank."""

import json
import re
import unicodedata


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def forgetting_check(case, reply, probes):
    if case["family"] != "forgetting":
        return {"applicable": False, "passed": True, "matches": []}
    # Frozen fixtures explicitly phrase their synthetic value after these
    # delimiters. This is a literal regression guard, not a paraphrase detector.
    parts = re.split(r"\s+(?:is|was)\s+|是|为", case["old"], maxsplit=1)
    value = normalized(parts[-1])
    if len(value) < 3:
        raise ValueError("Forgotten fixture value is too short for literal checking")
    texts = [("answer", reply)]
    memory = probes.get("memory") or {}
    texts.extend((f"memory/{i}", json.dumps(f, ensure_ascii=False)) for i, f in enumerate(memory.get("snapshot", [])))
    for i, item in enumerate(probes.get("checkpoints", [])):
        if case["old"] in item.get("forbidden", []):
            texts.append((f"checkpoint/{i}", json.dumps(item["snapshot"], ensure_ascii=False)))
    matches = [name for name, text in texts if value in normalized(text)]
    return {"applicable": True, "passed": not matches, "matches": matches,
            "limit": "Literal synthetic value only; paraphrases still require semantic review"}
