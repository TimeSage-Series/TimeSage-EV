"""Write instances/<period>/instance.json: the values for question_template.md's
placeholders, which the engine renders at run time."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import INSTANCES, release_month_label, data_month_label  # noqa: E402
from instance_file import write_instance  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-months", required=True)
    args = ap.parse_args()


    targets = [s.strip() for s in args.instance_months.split(",") if s.strip()]
    n = 0
    for label in targets:
        out_dir = INSTANCES / label
        if not out_dir.exists():
            print(f"[skip] {label}: missing", file=sys.stderr); continue
        yr, mo = int(label[:4]), int(label[5:])
        template_vars = {
            "period_long": release_month_label(yr, mo),
            "period_label": label,
            "release_label": label,
            "release_month_long": release_month_label(yr, mo),
            "data_month_long": data_month_label(yr, mo),
            "prior_year_data_month_long": data_month_label(yr - 1, mo),
        }
        write_instance(out_dir, template_vars)
        n += 1
        print(f"[ok]   {label}", flush=True)
    print(f"[done] wrote {n} instance.json files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
