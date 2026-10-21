"""Render per-instance question.md + copy answer_schema.json."""
from __future__ import annotations
import argparse
import csv
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES, iter_weeks, iso_label  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    template = (ENV / "question_template.md").read_text()
    schema   = ENV / "answer_schema.json"

    for y, w, _tue in iter_weeks(args.instance_start, args.instance_end):
        label = iso_label(y, w)
        inst = INSTANCES / label
        if not inst.exists(): continue
        ts_csv = inst / "timeseries.csv"
        if not ts_csv.exists(): continue
        last = None
        for last in csv.DictReader(ts_csv.open()): pass
        if last is None: continue
        rendered = (template
                    .replace("{{observation_date}}", last["observation_date"])
                    .replace("{{iso_week}}", last["iso_week"]))
        (inst / "question.md").write_text(rendered)
        shutil.copy(schema, inst / "answer_schema.json")
        print(f"[ok]  {label}", flush=True)


if __name__ == "__main__":
    main()
