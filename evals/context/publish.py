"""Export a small comparison summary for an explicitly selected dashboard home."""

import argparse
import json
from pathlib import Path


def summary(data):
    if data.get("experiment") != "context-memory-v5" or not isinstance(data.get("summary"), dict):
        raise ValueError("Expected a V5 comparison report")
    result = {k: data.get(k) for k in ("experiment", "status", "quality_status", "promotion_status", "trials", "summary")}
    source = data.get("source", {})
    result["source"] = {k: source.get(k) for k in ("commit", "manifest_sha256")}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--home", type=Path, required=True)
    args = parser.parse_args()
    data = summary(json.loads(args.report.read_text(encoding="utf-8")))
    args.home.mkdir(parents=True, exist_ok=True)
    target = args.home / "comparison_report.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    print(str(target))


if __name__ == "__main__":
    main()
