"""Read an existing audit/report; never submits or resumes a paid job."""
import argparse
import json
from collections import defaultdict
from pathlib import Path


def summarize(report):
    stages = defaultdict(lambda: {"calls": 0, "model_seconds": 0, "completion_tokens": 0})
    ocr = []
    for entry in report.get("audit", []):
        if entry.get("kind") == "model":
            row = stages[entry["stage"]]
            row["calls"] += 1
            row["model_seconds"] += entry.get("seconds", 0)
            row["completion_tokens"] += entry.get("usage", {}).get("completion_tokens", 0)
        if entry.get("kind") == "ocr" and entry.get("status") == "done":
            ocr.append({key: entry.get(key) for key in ("image_id", "elapsed_seconds", "cache_hit")})
    for row in stages.values():
        row["model_seconds"] = round(row["model_seconds"], 3)
    return {"status": report.get("status"), "total_seconds": report.get("seconds"),
            "model_stages": dict(stages), "ocr": ocr,
            "note": "model_seconds是接口往返耗时，包含生成及网络/服务端等待，不能单独归因为推理；输出token可能含思考token。"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(json.loads(args.report.read_text())), ensure_ascii=False, indent=2))
