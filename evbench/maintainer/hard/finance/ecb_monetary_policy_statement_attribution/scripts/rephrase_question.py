"""Render environment/question_template.md per instance.

Also copies answer_schema.json into each instance directory so the
instance is self-contained at the file level (except for
visible_reports.json, which references gt_source/ via the eval-harness
staging contract).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES, label_from_date, iter_meetings  # noqa

LANDING_PATH = Path(__file__).parent / "landing_urls.json"

TPL    = ENV / "question_template.md"
SCHEMA = ENV / "answer_schema.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    landing_data = json.loads(LANDING_PATH.read_text())
    meetings_all = landing_data["meeting_dates"]

    tpl = TPL.read_text()
    schema = SCHEMA.read_text()
    for d in iter_meetings(meetings_all, args.instance_start, args.instance_end):
        label = label_from_date(d)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}", flush=True)
            continue
        (out / "question.md").write_text(
            tpl.replace("{{meeting_label}}", label)
               .replace("{{publication_date}}", d.isoformat())
        )
        (out / "answer_schema.json").write_text(schema)
        print(f"[ok]  {label}", flush=True)


if __name__ == "__main__":
    main()
