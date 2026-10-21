"""Write instances/<period>/instance.json: the values for question_template.md's
placeholders, which the engine renders at run time."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import INSTANCES, week_label, iter_weeks, period_long  # noqa
from instance_file import write_instance  # noqa


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()


    for y, w, sunday in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(sunday)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}", flush=True); continue
        template_vars = {
            "period_long": period_long(y, w),
            "period_label": label,
            "week_ending": sunday.isoformat(),
        }
        write_instance(out, template_vars)
        print(f"[ok]  {label}", flush=True)


if __name__ == "__main__":
    main()
