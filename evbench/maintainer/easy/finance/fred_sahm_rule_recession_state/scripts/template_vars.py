"""Write instances/<period>/instance.json: the values for question_template.md's
placeholders, which the engine renders at run time."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (INSTANCES,
                     month_label, iter_months, last_of_month)  # noqa
from instance_file import write_instance  # noqa


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()


    for y, m, _ in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}", flush=True)
            continue
        period_end = last_of_month(y, m).isoformat()
        write_instance(out, {
            "period_long": label,
            "period_label": label,
            "month_label": label,
            "period_end": period_end,
        })
        print(f"[ok]  {label}", flush=True)


if __name__ == "__main__":
    main()
