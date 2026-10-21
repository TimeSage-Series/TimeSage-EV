"""Render environment/question_template.md per instance.

Also copies answer_schema.json into each instance directory so each
instance is self-contained at the file level (visible_reports.json
references gt_source/ via the eval-harness staging contract).
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (   # noqa: E402
    ENV, INSTANCES, iter_months, month_label, release_date_for,
    last_day_of_month,
)


TPL    = ENV / "question_template.md"
SCHEMA = ENV / "answer_schema.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    tpl = TPL.read_text()
    schema = SCHEMA.read_text()

    for y, m in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}", flush=True); continue
        release = release_date_for(y, m)
        valid = f"{label}-01 .. {last_day_of_month(y, m).isoformat()}"
        rendered = (
            tpl.replace("{{forecast_month_label}}", label)
               .replace("{{release_date}}", release.isoformat())
               .replace("{{valid_window}}", valid)
        )
        (out / "question.md").write_text(rendered)
        (out / "answer_schema.json").write_text(schema)
        print(f"[ok]  {label}", flush=True)


if __name__ == "__main__":
    main()
