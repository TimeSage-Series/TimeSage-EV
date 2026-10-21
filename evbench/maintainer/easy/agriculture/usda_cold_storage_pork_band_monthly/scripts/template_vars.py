"""Write instances/<period>/instance.json: the values for question_template.md's
placeholders, which the engine renders at run time."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    INSTANCES, month_to_folder, month_label,
    data_month_to_release,
)
from instance_file import write_instance  # noqa: E402


def parse_instance_label(s: str) -> tuple[int, int]:
    return int(s[:4]), int(s[5:])


def enumerate_months(start, end):
    y, m = start; ey, em = end
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12: m = 1; y += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()


    start = parse_instance_label(args.instance_start)
    end   = parse_instance_label(args.instance_end)
    n = 0
    for (yr, mo) in enumerate_months(start, end):
        folder = INSTANCES / month_to_folder(yr, mo)
        if not folder.exists(): continue
        period_lbl = f"{yr:04d}-{mo:02d}"
        data_long = month_label(yr, mo)
        rel_y, rel_m = data_month_to_release(yr, mo)
        rel_long = month_label(rel_y, rel_m)
        template_vars = {
            "period_label": period_lbl,
            "data_month_long": data_long,
            "release_month_long": rel_long,
        }
        write_instance(folder, template_vars)
        n += 1
        print(f"[ok] {folder.name}/instance.json ({rel_long} release, "
              f"{data_long} data)")
    print(f"[done] wrote {n} instance.json files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
