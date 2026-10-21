"""Render per-instance question.md + copy answer_schema.json into each instance."""
from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES, iter_months, month_label  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    template_path = ENV / "question_template.md"
    schema_path   = ENV / "answer_schema.json"
    template = template_path.read_text()

    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        inst = INSTANCES / label
        if not inst.exists():
            print(f"[skip] {label}: instance dir missing", flush=True); continue
        rendered = template.replace("{{report_month}}", label)
        (inst / "question.md").write_text(rendered)
        shutil.copy(schema_path, inst / "answer_schema.json")
        print(f"[ok]   {label}", flush=True)


if __name__ == "__main__":
    main()
