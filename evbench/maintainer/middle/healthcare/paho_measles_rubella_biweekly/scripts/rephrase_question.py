"""Render environment/question_template.md per instance.

Also copies answer_schema.json and country_vocabulary.json into each
instance directory so the instance is self-contained at the file level
(except for the visible_reports manifest, which references gt_source/).
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (ENV, INSTANCES, iter_biweekly_issues,
                     biweekly_label, paho_saturday)  # noqa


TPL    = ENV / "question_template.md"
SCHEMA = ENV / "answer_schema.json"
VOCAB  = ENV / "country_vocabulary.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    tpl = TPL.read_text()
    schema = SCHEMA.read_text()
    vocab = VOCAB.read_text()
    for y, w1, w2, _sat in iter_biweekly_issues(args.instance_start, args.instance_end):
        label = biweekly_label(y, w1, w2)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}", flush=True); continue
        sat = paho_saturday(y, w2)
        (out / "question.md").write_text(
            tpl.replace("{{issue_label}}", label)
               .replace("{{week_ending}}", sat.isoformat())
        )
        (out / "answer_schema.json").write_text(schema)
        (out / "country_vocabulary.json").write_text(vocab)
        print(f"[ok]  {label}", flush=True)


if __name__ == "__main__":
    main()
