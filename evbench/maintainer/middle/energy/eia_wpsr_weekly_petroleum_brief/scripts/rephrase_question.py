"""Render environment/question_template.md against each instance's variables.
Also copies environment/answer_schema.json into each instance directory.
"""
from __future__ import annotations
import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES  # noqa: E402


def render(template: str, period_end: str) -> str:
    # Instance dirs are now named by Friday period_end, so period_end == label.
    # Templates that historically used {{query_week}} still work (same value).
    return (template
            .replace("{{period_end}}", period_end)
            .replace("{{period_label}}", period_end)
            .replace("{{query_week}}", period_end))


def main() -> None:
    # CLI args are accepted for backward compat but ignored: instance dirs are
    # named by Friday period_end (created by `format.py timeseries`) and we just
    # walk INSTANCES directly.
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=False,
                    help="(ignored; kept for backward-compat CLI)")
    ap.add_argument("--instance-end",   required=False,
                    help="(ignored; kept for backward-compat CLI)")
    ap.parse_args()

    template = (ENV / "question_template.md").read_text()
    schema   = ENV / "answer_schema.json"

    for inst in sorted(INSTANCES.iterdir()):
        if not inst.is_dir(): continue
        label = inst.name
        gt_path = inst / "ground_truth.json"
        period_end = label
        if gt_path.exists():
            try:
                period_end = json.loads(gt_path.read_text()).get("period_end", label)
            except Exception:
                pass
        (inst / "question.md").write_text(render(template, period_end))
        shutil.copy(schema, inst / "answer_schema.json")
        print(f"[ok]  {label}", flush=True)


if __name__ == "__main__":
    main()
