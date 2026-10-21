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
import datetime as dt
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    TS_SOURCE, INSTANCES, parse_romi_ascii, classify_phase,
    iter_weeks, week_label, friday_of_iso_week,
)
import json
from _common import (  # noqa: E402
    INSTANCES, classify_phase, MJO_DASHBOARD_URL,
    iter_weeks, week_label,
)


# --- step: timeseries ----------------------------------------------------

# RMM1/RMM2 only. The amplitude is deliberately left out: `amplitude < 1`
# decides `weak`, so shipping it would hand over half the rule. The agent
# computes sqrt(rmm1^2 + rmm2^2) itself; the gt step does the same from the CSV.
CSV_COLUMNS = ["observation_date", "iso_week", "rmm1", "rmm2"]


def latest_source_text() -> str:
    snaps = sorted(TS_SOURCE.glob("romi-*.ascii.txt"))
    if not snaps:
        raise SystemExit("[error] no ROMI snapshots in timeseries_source/")
    return snaps[-1].read_text(encoding="utf-8")


def friday_sample(by_date: dict, year: int, week: int):
    """Return (obs_date, rmm1, rmm2) for the Friday of this ISO week or
    fall back to the most recent prior day in the same ISO week."""
    friday = friday_of_iso_week(year, week)
    for offset in range(0, 7):  # Friday..Saturday previous wk's tail (max 6 to stay in week)
        d = friday - dt.timedelta(days=offset)
        if d.isocalendar().week != week or d.isocalendar().year != year:
            break
        if d in by_date:
            r1, r2 = by_date[d]
            return d, r1, r2
    return None


def build_all_weekly_rows(by_date) -> list[dict]:
    """Walk every ISO week present in the source and assemble Friday-
    sampled rows in ascending order. Used to construct the full
    cumulative history each instance sees."""
    if not by_date:
        return []
    first_date = min(by_date.keys())
    last_date = max(by_date.keys())
    # Walk from the ISO week of first_date through last_date.
    fy, fw, _ = first_date.isocalendar()
    ly, lw, _ = last_date.isocalendar()
    rows = []
    cur = friday_of_iso_week(fy, fw)
    stop = friday_of_iso_week(ly, lw)
    while cur <= stop:
        iso = cur.isocalendar()
        y, w = iso.year, iso.week
        s = friday_sample(by_date, y, w)
        if s is None:
            cur += dt.timedelta(days=7)
            continue
        obs_date, r1, r2 = s
        amp, phase = classify_phase(r1, r2)
        rows.append({
            "observation_date": obs_date.isoformat(),
            "iso_week": f"{y:04d}-W{w:02d}",
            "rmm1": f"{r1:+.5f}",
            "rmm2": f"{r2:+.5f}",
            "amplitude": f"{amp:.5f}",
            "_sort_key": obs_date,
        })
        cur += dt.timedelta(days=7)
    rows.sort(key=lambda r: r["_sort_key"])
    for r in rows:
        r.pop("_sort_key")
    return rows


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True, help="YYYY-Www")
    ap.add_argument("--instance-end",   required=True, help="YYYY-Www")
    args = ap.parse_args()

    by_date = parse_romi_ascii(latest_source_text())
    all_rows = build_all_weekly_rows(by_date)
    by_week = {r["iso_week"]: r for r in all_rows}

    INSTANCES.mkdir(parents=True, exist_ok=True)
    n = 0
    for y, w, friday in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(friday)
        if label not in by_week:
            print(f"[warn] {label} not in ROMI source", file=sys.stderr)
            continue
        cum = []
        for r in all_rows:
            cum.append(r)
            if r["iso_week"] == label:
                break
        folder = INSTANCES / label
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "timeseries.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for r in cum:
                writer.writerow({k: r[k] for k in CSV_COLUMNS})
        last = cum[-1]
        n += 1
        print(f"[ok] {label}/timeseries.csv ({len(cum)} rows; latest "
              f"obs={last['observation_date']} rmm1={last['rmm1']} "
              f"rmm2={last['rmm2']} amp={last['amplitude']})")
    print(f"[done] wrote {n} per-instance CSVs")
    return 0


# --- step: gt ------------------------------------------------------------
def latest_row(csv_path: Path) -> dict:
    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return rows[-1]


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    n = 0
    for y, w, friday in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(friday)
        folder = INSTANCES / label
        csv_path = folder / "timeseries.csv"
        if not csv_path.exists():
            print(f"[skip] {label}", file=sys.stderr); continue
        row = latest_row(csv_path)
        r1 = float(row["rmm1"]); r2 = float(row["rmm2"])
        amp, phase = classify_phase(r1, r2)
        obs_date = row["observation_date"]

        (folder / "ground_truth.json").write_text(
            json.dumps({"mjo_phase": phase, "report": ""},
                       indent=2) + "\n", encoding="utf-8")

        evidence = (
            "# Ground-truth evidence -- NOAA PSL MJO weekly phase\n\n"
            f"## Instance ISO week: {label} (Friday sample {obs_date})\n\n"
            f"- **RMM1** = **{row['rmm1']}**\n"
            f"- **RMM2** = **{row['rmm2']}**\n"
            f"- **Amplitude** = sqrt(RMM1^2 + RMM2^2) = **{amp:.4f}**\n"
            f"- Source row in `timeseries.csv`: "
            f"`observation_date={row['observation_date']}, "
            f"iso_week={row['iso_week']}, "
            f"rmm1={row['rmm1']}, rmm2={row['rmm2']}`\n"
            f"- Applied per-week rule:\n"
            f"  - amplitude < 1.0 -> `weak`\n"
            f"  - else: 8-sector Wheeler-Hendon phase wheel (phase_1..phase_8)\n"
            f"- **Derived MJO phase: `{phase}`**\n\n"
            "## Traceability\n\n"
            "- Raw time series: NOAA PSL ROMI ascii file at "
            "https://www.psl.noaa.gov/mjo/mjoindex/romi.cpcolr.1x.txt\n"
            "- Sign/order mapping: RMM1 = ROMI_PC2, RMM2 = -ROMI_PC1 "
            "(per PSL convention).\n"
            f"- Public reference for the rule: NOAA PSL MJO dashboard "
            f"at {MJO_DASHBOARD_URL}\n"
        )
        (folder / "gt_evidence.md").write_text(evidence, encoding="utf-8")
        n += 1
        print(f"[ok] {label}: amp={amp:.2f} -> {phase}")
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
