#!/usr/bin/env python3
"""Build instances for this scenario's this scenario.

    python scripts/format.py                 # every step, in order: timeseries -> gt
    python scripts/format.py timeseries    # one step
    python scripts/format.py gt [flags]    # …with that step's own flags
    python scripts/format.py all [flags]     # every step, flags forwarded to each
    python scripts/format.py --list          # list the steps

Merged from format_timeseries.py and format_gt.py. Each step keeps the argument
parser it had before, so every flag that used to work still works — pass it
after the step name.
"""
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    TS_SOURCE, INSTANCES, parse_oni_ascii, classify_phase,
    SEASON_CENTERED_MONTH, season_to_folder, season_label,
)
import json
from _common import (  # noqa: E402
    INSTANCES, classify_phase, SEASON_CENTERED_MONTH,
    ONI_DASHBOARD_URL, season_to_folder, season_label,
)


# --- step: timeseries ----------------------------------------------------

CSV_COLUMNS = [
    "season", "year", "season_label", "centered_month",
    "nino34_total_c", "nino34_anomaly_c",
]


def latest_source_text() -> str:
    snaps = sorted(TS_SOURCE.glob("oni-*.ascii.txt"))
    if not snaps:
        raise SystemExit(
            "[error] no ONI source snapshots in timeseries_source/ — "
            "run `download.py timeseries` first."
        )
    return snaps[-1].read_text(encoding="utf-8")


def parse_instance_label(s: str) -> tuple[int, str]:
    """Parse a 'YYYY-SEAS' instance label into (year, season_code)."""
    s = s.strip()
    if len(s) != 8 or s[4] != "-":
        raise ValueError(f"bad instance label {s!r} — expected 'YYYY-SEAS'")
    year_s, season = s[:4], s[5:]
    if season not in SEASON_CENTERED_MONTH:
        raise ValueError(f"bad season code in {s!r}: {season}")
    return int(year_s), season


def season_sort_key(year: int, season: str) -> tuple[int, int]:
    """Calendar-order sort key for (year, season)."""
    return (year, SEASON_CENTERED_MONTH[season])


def enumerate_instance_seasons(
    start: tuple[int, str], end: tuple[int, str]
) -> list[tuple[int, str]]:
    """All seasons in calendar order from start to end inclusive."""
    out: list[tuple[int, str]] = []
    codes = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ",
             "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]
    s_year, s_season = start
    e_year, e_season = end
    s_idx = codes.index(s_season)
    e_idx = codes.index(e_season)

    cur_year = s_year
    cur_idx = s_idx
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


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--instance-start", required=True,
        help="First instance season, format YYYY-SEAS (e.g. 2024-MAM).",
    )
    ap.add_argument(
        "--instance-end", required=True,
        help="Last instance season, format YYYY-SEAS (e.g. 2026-FMA).",
    )
    args = ap.parse_args()

    start = parse_instance_label(args.instance_start)
    end = parse_instance_label(args.instance_end)
    if season_sort_key(*start) > season_sort_key(*end):
        raise SystemExit("[error] --instance-start must be ≤ --instance-end")

    text = latest_source_text()
    rows = parse_oni_ascii(text)
    if not rows:
        raise SystemExit("[error] parsed 0 rows from source snapshot")

    # Annotate rows with sort key + derived phase for downstream filtering.
    for r in rows:
        r["_key"] = season_sort_key(r["year"], r["season"])
        r["derived_phase"] = classify_phase(r["anomaly_c"])
    rows.sort(key=lambda r: r["_key"])

    INSTANCES.mkdir(parents=True, exist_ok=True)
    instance_seasons = enumerate_instance_seasons(start, end)
    n_written = 0
    for (yr, sn) in instance_seasons:
        key = season_sort_key(yr, sn)
        if not any(r["_key"] == key for r in rows):
            print(f"[warn] instance season {season_label(sn, yr)} not in "
                  f"source data — skipping", file=sys.stderr)
            continue
        cumulative = [r for r in rows if r["_key"] <= key]
        folder = INSTANCES / season_to_folder(sn, yr)
        folder.mkdir(parents=True, exist_ok=True)
        out_csv = folder / "timeseries.csv"
        with out_csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(CSV_COLUMNS)
            for r in cumulative:
                w.writerow([
                    r["season"],
                    r["year"],
                    f"{r['year']:04d}-{r['season']}",
                    SEASON_CENTERED_MONTH[r["season"]],
                    f"{r['total_sst_c']:.2f}",
                    f"{r['anomaly_c']:.2f}",
                ])
        n_written += 1
        print(f"[ok] {folder.name}/timeseries.csv "
              f"({len(cumulative)} rows; latest "
              f"{r['season']} {r['year']} anom={r['anomaly_c']:+.2f})")
    print(f"[done] wrote {n_written} per-instance CSVs")
    return 0


# --- step: gt ------------------------------------------------------------
def parse_instance_label__gt(s: str) -> tuple[int, str]:
    s = s.strip()
    if len(s) != 8 or s[4] != "-":
        raise ValueError(f"bad instance label {s!r}")
    return int(s[:4]), s[5:]


def season_sort_key__gt(year: int, season: str) -> tuple[int, int]:
    return (year, SEASON_CENTERED_MONTH[season])


def enumerate_instance_seasons__gt(start, end):
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


def latest_row(csv_path: Path) -> dict:
    with csv_path.open(encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        rows = list(rd)
    if not rows:
        raise SystemExit(f"[error] {csv_path} is empty")
    return rows[-1]


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    start = parse_instance_label__gt(args.instance_start)
    end = parse_instance_label__gt(args.instance_end)

    n = 0
    for (yr, sn) in enumerate_instance_seasons__gt(start, end):
        folder = INSTANCES / season_to_folder(sn, yr)
        csv_path = folder / "timeseries.csv"
        if not csv_path.exists():
            print(f"[skip] {folder.name}/timeseries.csv missing — run "
                  f"`format.py timeseries` first", file=sys.stderr)
            continue

        row = latest_row(csv_path)
        anomaly = float(row["nino34_anomaly_c"])
        season_lbl = season_label(sn, yr)         # "FMA 2026"
        period_label = f"{yr:04d}-{sn}"           # "2026-FMA"
        phase = classify_phase(anomaly)

        gt = {
            "enso_phase": phase,
            "report": "",
        }
        (folder / "ground_truth.json").write_text(
            json.dumps(gt, indent=2) + "\n", encoding="utf-8"
        )

        evidence = (
            "# Ground-truth evidence — NOAA CPC ONI ENSO phase\n\n"
            f"## Instance season: {season_lbl}\n\n"
            f"- **ONI anomaly (Niño 3.4 SST, °C)** = "
            f"**{row['nino34_anomaly_c']}**\n"
            f"- Source row in `timeseries.csv`: "
            f"`season={row['season']}, year={row['year']}, "
            f"season_label={row['season_label']}, "
            f"nino34_anomaly_c={row['nino34_anomaly_c']}`\n"
            f"- Applied per-season rule:\n"
            f"  - anomaly ≥ +0.5 °C → `El Nino`\n"
            f"  - anomaly ≤ -0.5 °C → `La Nina`\n"
            f"  - otherwise → `ENSO-Neutral`\n"
            f"- **Derived ENSO phase: `{phase}`**\n\n"
            "## Traceability\n\n"
            f"- Raw time series: NOAA CPC ONI ascii file at "
            f"https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt — "
            f"columns SEAS YR TOTAL ANOM; the ANOM column is the ONI.\n"
            f"- Public reference for the rule: NOAA CPC ONI dashboard at "
            f"{ONI_DASHBOARD_URL} — the colored-table view of the same "
            f"ANOM series (red = warm ≥ +0.5, blue = cool ≤ -0.5, "
            f"white = ENSO-Neutral).\n"
        )
        (folder / "gt_evidence.md").write_text(evidence, encoding="utf-8")

        n += 1
        print(f"[ok] {folder.name}: anom={anomaly:+.2f} → {phase}")
    print(f"[done] wrote {n} ground-truth files")
    return 0

# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------

#: Execution order. The ground truth is derived from the series, so timeseries runs first.
STEPS = ("timeseries", "gt")

_STEP_FUNCS = {
    "timeseries": _step_timeseries,
    "gt": _step_gt,
}


def _run_step(step: str, args: list) -> int:
    """Invoke one step with `args` as its argv, then restore the real argv."""
    saved = sys.argv
    sys.argv = [f"{Path(__file__).name} {step}"] + list(args)
    try:
        return int(_STEP_FUNCS[step]() or 0)
    finally:
        sys.argv = saved


def main() -> int:
    argv = sys.argv[1:]

    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv and argv[0] == "--list":
        for step in STEPS:
            print(step)
        return 0

    if argv and argv[0] in STEPS:
        return _run_step(argv[0], argv[1:])

    # No step named: run all of them. Bare invocation passes no flags; an
    # explicit `all` forwards whatever follows to every step.
    rest = argv[1:] if (argv and argv[0] == "all") else []
    if argv and argv[0] != "all":
        print(f"unknown step {argv[0]!r}; expected one of {', '.join(STEPS)}, "
              f"or 'all'", file=sys.stderr)
        return 2

    for step in STEPS:
        rc = _run_step(step, rest)
        if rc:
            print(f"[{Path(__file__).name}] step {step!r} exited {rc}; stopping",
                  file=sys.stderr)
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
