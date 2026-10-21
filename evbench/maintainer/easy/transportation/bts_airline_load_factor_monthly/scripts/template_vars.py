"""Write instances/<period>/instance.json: the values for question_template.md's
placeholders, which the engine renders at run time."""
from __future__ import annotations
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import INSTANCES, query_months
from instance_file import write_instance


def long_label(month_label: str) -> str:
    y, m = month_label.split("-")
    dt_ = datetime(int(y), int(m), 1)
    return dt_.strftime("%B %Y")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()
    months = query_months(args.instance_start, args.instance_end)
    for q in months:
        inst_dir = INSTANCES / q
        if not inst_dir.exists():
            continue
        template_vars = {
            "period_label": q,
            "period_long": long_label(q),
        }
        write_instance(inst_dir, template_vars)
        print(f"wrote {inst_dir/'instance.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
