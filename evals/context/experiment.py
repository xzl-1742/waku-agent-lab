"""Frozen V5 policy map, independent of application configuration imports."""

import hashlib
import json
from pathlib import Path

MANIFEST = Path(__file__).with_name("v5_manifest.json")


def manifest():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    from evals.context.fixtures import FIXTURES

    if hashlib.sha256(FIXTURES.read_text(encoding="utf-8").encode()).hexdigest() != data["fixture_sha256"]:
        raise ValueError("V5 fixture hash changed")
    return data


def policies(configuration):
    if configuration.startswith("V5-"):
        return dict(manifest()["arms"][configuration[3:]])
    return {"context_policy": {"A": "window", "B": "budget", "B2": "compact",
                                "V3-window": "window", "V3-compact": "compact"}[configuration],
            "memory_policy": "lifecycle" if configuration.startswith("V3-") else "legacy",
            "retrieval_policy": "legacy"}
