"""Render per-instance question.md + copy answer_schema.json into each instance."""
from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES, iter_months, long_month_label, month_label  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    template = (ENV / "question_template.md").read_text(encoding="utf-8")
    schema_path = ENV / "answer_schema.json"

    n_written = 0
    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        inst = INSTANCES / label
        if not inst.exists():
            print(f"[skip] {label}: instance dir missing")
            continue
        rendered = (template
                    .replace("{{period_label}}", label)
                    .replace("{{month_label_long}}", long_month_label(label)))
        (inst / "question.md").write_text(rendered, encoding="utf-8")
        shutil.copy(schema_path, inst / "answer_schema.json")
        n_written += 1
        print(f"[ok]   {label}")
    print(f"rendered {n_written} question.md / answer_schema.json instances")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
