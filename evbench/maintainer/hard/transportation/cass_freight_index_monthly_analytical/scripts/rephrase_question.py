"""Render the per-instance question.md from environment/question_template.md.

Also copies environment/answer_schema.json into each instance dir, since
the question references /root/answer_schema.json.
"""
from __future__ import annotations
import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES, iter_months, month_label  # noqa: E402

MONTHS_FULL = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def next_month_name(label: str) -> str:
    y, m = (int(x) for x in label.split("-"))
    d = dt.date(y, m, 1)
    nm = (d.month % 12) + 1
    return MONTHS_FULL[nm - 1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", default="2024-04")
    ap.add_argument("--instance-end",   default="2026-03")
    args = ap.parse_args()

    tpl = (ENV / "question_template.md").read_text()
    schema = (ENV / "answer_schema.json").read_text()

    n = 0
    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        inst = INSTANCES / label
        if not (inst / "timeseries.csv").exists():
            continue
        body = (
            tpl
            .replace("{{period}}", label)
            .replace("{{next_month}}", next_month_name(label))
        )
        (inst / "question.md").write_text(body)
        (inst / "answer_schema.json").write_text(schema)
        n += 1
    print(f"[done] rendered {n} question.md + answer_schema.json files", flush=True)


if __name__ == "__main__":
    main()
