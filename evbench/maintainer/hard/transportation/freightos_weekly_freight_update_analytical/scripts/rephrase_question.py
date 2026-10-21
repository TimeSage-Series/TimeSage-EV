"""Render per-instance question.md + copy answer_schema.json into each instance."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=24)
    args = ap.parse_args()

    tpl = (ENV / "question_template.md").read_text()
    schema = (ENV / "answer_schema.json").read_text()
    metrics = json.loads(
        (Path(__file__).parent / "_parsed_metrics.json").read_text())
    dates = sorted(metrics)[-args.count:]

    n = 0
    for d in dates:
        inst = INSTANCES / d
        if not (inst / "timeseries.csv").exists():
            continue
        body = tpl.replace("{{publication_date}}", d)
        (inst / "question.md").write_text(body)
        (inst / "answer_schema.json").write_text(schema)
        n += 1
    print(f"[done] rendered {n}", flush=True)


if __name__ == "__main__":
    main()
