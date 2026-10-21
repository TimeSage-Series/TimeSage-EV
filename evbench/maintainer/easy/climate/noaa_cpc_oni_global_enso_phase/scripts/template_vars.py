"""Write instances/<period>/instance.json: the values for question_template.md's
placeholders, which the engine renders at run time."""
from __future__ import annotations
import argparse
import calendar
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    INSTANCES, SEASON_CENTERED_MONTH,
    season_to_folder, season_label,
)
from instance_file import write_instance  # noqa: E402


def parse_instance_label(s: str) -> tuple[int, str]:
    s = s.strip()
    if len(s) != 8 or s[4] != "-":
        raise ValueError(f"bad instance label {s!r}")
    return int(s[:4]), s[5:]


def enumerate_instance_seasons(start, end):
    codes = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ",
             "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]
    out = []
    s_year, s_season = start
    e_year, e_season = end
    cur_year, cur_idx = s_year, codes.index(s_season)
    e_idx = codes.index(e_season)
    while True:
        out.append((cur_year, codes[cur_idx]))
        if cur_year == e_year and cur_idx == e_idx:
            break
        cur_idx += 1
        if cur_idx >= 12:
            cur_idx = 0
            cur_year += 1
        if (cur_year, cur_idx) > (e_year, e_idx):
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()


    start = parse_instance_label(args.instance_start)
    end = parse_instance_label(args.instance_end)

    n = 0
    for (yr, sn) in enumerate_instance_seasons(start, end):
        folder = INSTANCES / season_to_folder(sn, yr)
        if not folder.exists():
            print(f"[skip] {folder.name}/ missing", file=sys.stderr)
            continue
        season_lbl = season_label(sn, yr)
        period_lbl = f"{yr:04d}-{sn}"
        centered_month_long = (
            f"{calendar.month_name[SEASON_CENTERED_MONTH[sn]]} {yr:04d}"
        )

        template_vars = {
            "season_label": season_lbl,
            "period_long": centered_month_long,
            "period_label": folder.name,
            "centered_month": centered_month_long,
        }
        write_instance(folder, template_vars)
        n += 1
        print(f"[ok] {folder.name}/instance.json ({season_lbl})")
    print(f"[done] wrote {n} instance.json files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
