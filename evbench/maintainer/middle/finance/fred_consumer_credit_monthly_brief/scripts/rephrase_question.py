"""Render environment/question_template.md against per-instance variables."""
from __future__ import annotations
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES, QUERY_MONTHS


def long_label(month_label: str) -> str:
    y, m = month_label.split("-")
    return datetime(int(y), int(m), 1).strftime("%B %Y")


def main() -> int:
    template_path = ENV / "question_template.md"
    if not template_path.exists():
        print(f"MISSING: {template_path}", file=sys.stderr)
        return 1
    template = template_path.read_text()
    for q in QUERY_MONTHS:
        inst_dir = INSTANCES / q
        if not inst_dir.exists():
            continue
        rendered = (
            template.replace("{{period_label}}", q)
            .replace("{{period_long}}", long_label(q))
        )
        (inst_dir / "question.md").write_text(rendered)
        print(f"rendered {inst_dir/'question.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
