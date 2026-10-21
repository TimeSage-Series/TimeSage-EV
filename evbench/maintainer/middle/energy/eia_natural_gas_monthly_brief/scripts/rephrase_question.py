"""Per-instance question.md + schema."""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES, iter_months, month_label, last_of_month  # noqa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()
    tpl = (ENV / "question_template.md").read_text()
    schema = (ENV / "answer_schema.json").read_text()
    vocab = (ENV / "sector_vocabulary.json").read_text()
    for y, m, _ in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}", flush=True); continue
        end = last_of_month(y, m)
        (out / "question.md").write_text(
            tpl
            .replace("{{issue_label}}", label)
            .replace("{{month_label}}", label)  # back-compat
            .replace("{{period_end}}", end.isoformat())
        )
        (out / "answer_schema.json").write_text(schema)
        (out / "sector_vocabulary.json").write_text(vocab)
        print(f"[ok]  {label}", flush=True)


if __name__ == "__main__":
    main()
