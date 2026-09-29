"""Optional offline lexical/vector fusion experiment; never changes Waku defaults.

Supply precomputed vectors with an explicit model/source and measured usage.
This module makes no embedding calls and adds no dependency. Missing vectors
leave the experiment unavailable; handwritten vectors test mechanics only.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

CASES = Path(__file__).with_name("hybrid_cases.json")


def cosine(a, b):
    if not a or len(a) != len(b) or any(type(x) not in (float, int) or not math.isfinite(x) for x in [*a, *b]):
        raise ValueError("Vectors must have equal nonzero dimensions and finite numbers")
    norm = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0


def fusion(lexical_ids, vector_ids, eligible, k=4):
    # Eligibility precedes both rank calculation and fusion. A supplied vector
    # cannot resurrect an excluded source, even with the highest similarity.
    scores = {}
    for ids in (lexical_ids, vector_ids):
        filtered = list(dict.fromkeys(i for i in ids if i in eligible))
        for rank, key in enumerate(filtered, 1):
            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
    return sorted(scores, key=lambda key: (-scores[key], key))[:k]


def report(vectors=None, split="development", minimum_similarity=.65):
    from waku.memory.lexical import relevance, terms

    bank = json.loads(CASES.read_text(encoding="utf-8"))
    metadata = {"experiment": bank["experiment"], "fixture_sha256": hashlib.sha256(CASES.read_bytes()).hexdigest(),
                "quality_status": "incomplete", "production_enabled": False}
    if vectors is None:
        return {**metadata, "status": "unavailable", "reason": "No measured embedding artifact supplied", "cases": []}
    if not vectors.get("model") or not vectors.get("source"):
        raise ValueError("Embedding artifacts require model and source provenance")
    rows = []
    for case in bank["cases"]:
        if split != "all" and case["split"] != split:
            continue
        data = vectors["cases"][case["id"]]
        eligible = set(case["records"]) - set(case.get("excluded", []))
        query_terms = terms(case["query"])
        lexical = sorted(((key, relevance(query_terms, text)) for key, text in case["records"].items() if key in eligible),
                         key=lambda pair: (-pair[1], pair[0]))
        lexical = [key for key, score in lexical if score]
        ranked = sorted(((key, cosine(data["query"], data["records"][key])) for key in eligible), key=lambda pair: (-pair[1], pair[0]))
        ids = fusion(lexical, [key for key, score in ranked if score >= minimum_similarity], eligible)
        gold = set(case["gold"])
        rows.append({"id": case["id"], "lexical_ids": lexical, "hybrid_ids": ids,
                     "lexical_recall": len(set(lexical) & gold) / len(gold) if gold else None,
                     "hybrid_recall": len(set(ids) & gold) / len(gold) if gold else None,
                     "unknown_false_positive": bool(ids and not gold), "excluded_ids": list(set(ids) - eligible)})
    return {**metadata, "status": "complete", "model": vectors["model"], "source": vectors["source"],
            "usage": vectors.get("usage"), "minimum_similarity": minimum_similarity,
            "vectors_sha256": hashlib.sha256(json.dumps(vectors, sort_keys=True).encode()).hexdigest(), "cases": rows,
            "limits": ["This compares ranking only; production packing and answer quality are unmeasured.",
                       "Synthetic vectors establish fusion mechanics, not semantic quality or a model recommendation."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path)
    parser.add_argument("--split", choices=("development", "reserved", "all"), default="development")
    parser.add_argument("--output", type=Path, default=Path("eval-results/v5-hybrid.json"))
    args = parser.parse_args()
    from evals.isolation import install

    install()
    data = json.loads(args.vectors.read_text(encoding="utf-8")) if args.vectors else None
    result = report(data, args.split)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "quality_status": result["quality_status"]}))


if __name__ == "__main__":
    main()
