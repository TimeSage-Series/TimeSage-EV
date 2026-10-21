"""Render environment/question_template.md per instance.

Also copies answer_schema.json into each instance directory so the instance
is self-contained at the file level (except for visible_reports.json, whose
referenced PDFs are staged at runtime by the eval harness).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES, iter_months, month_label  # noqa: E402

LANDING_PATH = Path(__file__).parent / "landing_urls.json"

TPL    = ENV / "question_template.md"
SCHEMA = ENV / "answer_schema.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    tpl = TPL.read_text()
    schema_text = SCHEMA.read_text()

    data = json.loads(LANDING_PATH.read_text())
    pub_dates = {k: v.get("published_approx") for k, v in data["issues"].items()}

    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        inst = INSTANCES / label
        if not inst.exists():
            continue
        pub = pub_dates.get(label) or (label + "-15")
        rendered = (tpl
                    .replace("{{issue_label}}", label)
                    .replace("{{publication_date}}", pub))
        (inst / "question.md").write_text(rendered)
        (inst / "answer_schema.json").write_text(schema_text)
        print(f"[ok]   {label}", flush=True)


if __name__ == "__main__":
    main()
