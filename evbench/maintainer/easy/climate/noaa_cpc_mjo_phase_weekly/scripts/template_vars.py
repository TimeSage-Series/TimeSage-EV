"""Write instances/<period>/instance.json: the values for question_template.md's
placeholders, which the engine renders at run time."""
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import INSTANCES, iter_weeks, week_label  # noqa: E402
from instance_file import write_instance  # noqa: E402


def latest_obs_date(csv_path: Path) -> str:
    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return rows[-1]["observation_date"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()


    n = 0
    for y, w, friday in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(friday)
        folder = INSTANCES / label
        if not folder.exists(): continue
        csv_path = folder / "timeseries.csv"
        if not csv_path.exists(): continue
        obs_date = latest_obs_date(csv_path)
        template_vars = {
            "iso_week_label": label,
            "week_ending": obs_date,
        }
        write_instance(folder, template_vars)
        n += 1
        print(f"[ok] {label}/instance.json (obs {obs_date})")
    print(f"[done] wrote {n} instance.json files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
