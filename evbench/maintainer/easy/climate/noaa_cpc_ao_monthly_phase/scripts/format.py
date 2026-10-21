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
    TS_SOURCE, INSTANCES, parse_ao_ascii, classify_phase, month_to_folder,
)
import json
from _common import (  # noqa: E402
    INSTANCES, classify_phase, AO_DASHBOARD_URL,
    month_to_folder, month_label,
)


# --- step: timeseries ----------------------------------------------------

CSV_COLUMNS = ["year", "month", "period_label", "ao_value"]


def parse_instance_label(s: str) -> tuple[int, int]:
    s = s.strip()
    if len(s) != 7 or s[4] != "-":
        raise ValueError(f"bad instance label {s!r} -- expected 'YYYY-MM'")
    return int(s[:4]), int(s[5:])


def enumerate_months(start, end):
    y, m = start; ey, em = end
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m = 1; y += 1


def latest_source_text() -> str:
    snaps = sorted(TS_SOURCE.glob("ao-*.ascii.txt"))
    if not snaps:
        raise SystemExit("[error] no AO source snapshots in timeseries_source/")
    return snaps[-1].read_text(encoding="utf-8")


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True, help="YYYY-MM")
    ap.add_argument("--instance-end",   required=True, help="YYYY-MM")
    args = ap.parse_args()

    start = parse_instance_label(args.instance_start)
    end   = parse_instance_label(args.instance_end)
    if start > end:
        raise SystemExit("[error] start must be <= end")

    rows = parse_ao_ascii(latest_source_text())
    for r in rows:
        r["derived_phase"] = classify_phase(r["ao_value"])
    rows.sort(key=lambda r: (r["year"], r["month"]))

    INSTANCES.mkdir(parents=True, exist_ok=True)
    n = 0
    for (yr, mo) in enumerate_months(start, end):
        key = (yr, mo)
        if not any((r["year"], r["month"]) == key for r in rows):
            print(f"[warn] {yr:04d}-{mo:02d} not in source", file=sys.stderr); continue
        cum = [r for r in rows if (r["year"], r["month"]) <= key]
        folder = INSTANCES / month_to_folder(yr, mo)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "timeseries.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(CSV_COLUMNS)
            for r in cum:
                w.writerow([r["year"], r["month"],
                            f"{r['year']:04d}-{r['month']:02d}",
                            f"{r['ao_value']:.4f}"])
        last = cum[-1]
        n += 1
        print(f"[ok] {folder.name}/timeseries.csv ({len(cum)} rows; latest "
              f"{last['year']:04d}-{last['month']:02d} ao={last['ao_value']:+.2f})")
    print(f"[done] wrote {n} per-instance CSVs")
    return 0


# --- step: gt ------------------------------------------------------------
def parse_instance_label__gt(s: str) -> tuple[int, int]:
    return int(s[:4]), int(s[5:])


def latest_row(csv_path: Path) -> dict:
    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return rows[-1]


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    start = parse_instance_label__gt(args.instance_start)
    end   = parse_instance_label__gt(args.instance_end)
    n = 0
    for (yr, mo) in enumerate_months(start, end):
        folder = INSTANCES / month_to_folder(yr, mo)
        csv_path = folder / "timeseries.csv"
        if not csv_path.exists():
            print(f"[skip] {folder.name}", file=sys.stderr); continue
        row = latest_row(csv_path)
        ao = float(row["ao_value"])
        period_label = f"{yr:04d}-{mo:02d}"
        phase = classify_phase(ao)

        (folder / "ground_truth.json").write_text(
            json.dumps({"ao_phase": phase, "report": ""},
                       indent=2) + "\n", encoding="utf-8")

        evidence = (
            "# Ground-truth evidence -- NOAA CPC AO monthly phase\n\n"
            f"## Instance month: {month_label(yr, mo)} ({period_label})\n\n"
            f"- **AO monthly index** = **{row['ao_value']}** "
            f"(standardised SLP anomaly, sigma-units, base 1979-2000)\n"
            f"- Source row in `timeseries.csv`: "
            f"`year={row['year']}, month={row['month']}, "
            f"period_label={row['period_label']}, ao_value={row['ao_value']}`\n"
            f"- Applied per-month rule:\n"
            f"  - ao_value >= +0.5 -> `Positive`\n"
            f"  - ao_value <= -0.5 -> `Negative`\n"
            f"  - otherwise -> `Neutral`\n"
            f"- **Derived AO phase: `{phase}`**\n\n"
            "## Traceability\n\n"
            "- Raw time series: NOAA CPC AO ascii file at "
            "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/daily_ao_index/"
            "monthly.ao.index.b50.current.ascii\n"
            f"- Public reference for the rule: NOAA CPC AO dashboard at "
            f"{AO_DASHBOARD_URL}\n"
        )
        (folder / "gt_evidence.md").write_text(evidence, encoding="utf-8")
        n += 1
        print(f"[ok] {folder.name}: ao={ao:+.2f} -> {phase}")
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
