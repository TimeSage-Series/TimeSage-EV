"""Render per-instance question.md from environment/question_template.md."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES, iter_months, month_long  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    template = (ENV / "question_template.md").read_text(encoding="utf-8")
    schema = (ENV / "answer_schema.json").read_text(encoding="utf-8")

    n = 0
    for period in iter_months(args.instance_start, args.instance_end):
        folder = INSTANCES / period
        if not folder.exists():
            continue
        rendered = (
            template
            .replace("{{period}}", period)
            .replace("{{month_long}}", month_long(period))
        )
        (folder / "question.md").write_text(rendered, encoding="utf-8")
        (folder / "answer_schema.json").write_text(schema, encoding="utf-8")
        n += 1
        print(f"[ok]  {period}: {month_long(period)}")
    print(f"[done] rendered {n} questions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
