"""Render environment/question_template.md per month."""
from __future__ import annotations
import sys
from _common import INSTANCES, ENV, REPORT_MONTHS


def main() -> int:
    template = (ENV / "question_template.md").read_text()
    n = 0
    for y, m in REPORT_MONTHS:
        lbl = f"{y}-{m:02d}"
        inst = INSTANCES / lbl
        if not inst.exists():
            continue
        (inst / "question.md").write_text(template.replace("{{report_month}}", lbl))
        n += 1
    print(f"rendered {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
