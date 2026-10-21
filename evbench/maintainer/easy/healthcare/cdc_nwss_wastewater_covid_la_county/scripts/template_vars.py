"""Write instances/<period>/instance.json: the values for question_template.md's
placeholders, which the engine renders at run time."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import INSTANCES, week_label, iter_weeks  # noqa
from instance_file import write_instance  # noqa


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()


    for y, w, sat in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(sat)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}", flush=True); continue
        write_instance(out, {
            "period_label": label,
            "iso_week_label": label,
            "week_ending": sat.isoformat(),
        })
        print(f"[ok]  {label}", flush=True)


if __name__ == "__main__":
    main()
