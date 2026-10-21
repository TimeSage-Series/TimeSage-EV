"""Render environment/question_template.md per instance.

Also copies answer_schema.json into each instance directory so the instance
is self-contained at the file level (except for visible_reports.json, which
references gt_source/ via the eval-harness staging contract).
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES, iter_months, month_label, last_day_of_month  # noqa


TPL    = ENV / "question_template.md"
SCHEMA = ENV / "answer_schema.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    tpl = TPL.read_text()
    schema = SCHEMA.read_text()
    for y, m, _last in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}", flush=True); continue
        period_end = last_day_of_month(y, m)
        (out / "question.md").write_text(
            tpl.replace("{{iso_month_label}}", label).replace("{{period_end}}", period_end.isoformat())
        )
        (out / "answer_schema.json").write_text(schema)
        print(f"[ok]  {label}", flush=True)


if __name__ == "__main__":
    main()
