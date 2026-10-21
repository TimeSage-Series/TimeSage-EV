"""Render environment/question_template.md per query month."""
from __future__ import annotations
import sys
from _common import INSTANCES, ENV, REPORT_MONTHS, ym_label


def main() -> int:
    template = (ENV / "question_template.md").read_text()
    n = 0
    for y, m in REPORT_MONTHS:
        lbl = ym_label(y, m)
        inst = INSTANCES / lbl
        if not inst.exists():
            continue
        rendered = template.replace("{{data_month}}", lbl)
        (inst / "question.md").write_text(rendered)
        n += 1
    print(f"rendered {n} questions", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
