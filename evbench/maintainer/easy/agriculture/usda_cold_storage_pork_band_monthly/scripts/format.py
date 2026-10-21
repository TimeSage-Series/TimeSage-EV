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
import statistics
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    TS_SOURCE, INSTANCES, classify_band,
    mmyy_to_release_month, release_to_data_month,
    month_to_folder,
)
from _pdf_parser import parse_pork_stocks  # noqa: E402
import json
from _common import (  # noqa: E402
    INSTANCES, classify_band, LANDING_BASE,
    month_to_folder, month_label,
)


# --- step: timeseries ----------------------------------------------------

# Levels only. The same-month 5-year min / mean / sigma are deliberately left
# out: the band is a cut on them, so shipping them would turn the task into a
# column lookup. The agent has to pull the reference window from the history.
CSV_COLUMNS = [
    "data_year", "data_month", "period_label", "pork_stocks_mlb",
]


def parse_instance_label(s: str) -> tuple[int, int]:
    return int(s[:4]), int(s[5:])


def enumerate_months(start, end):
    y, m = start; ey, em = end
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12: m = 1; y += 1


def harvest_pork_history() -> list[dict]:
    """Parse every cost*.pdf in timeseries_source/. Returns rows
    sorted by data month ascending."""
    rows = []
    for pdf in sorted(TS_SOURCE.glob("cost*.pdf")):
        mmyy = pdf.stem.replace("cost", "")
        try:
            rel_y, rel_m = mmyy_to_release_month(mmyy)
        except ValueError:
            print(f"[warn] bad filename {pdf.name}", file=sys.stderr); continue
        data_y, data_m = release_to_data_month(rel_y, rel_m)
        try:
            stocks_klb = parse_pork_stocks(pdf)
        except Exception as e:
            print(f"[warn] parse failed {pdf.name}: {e}", file=sys.stderr); continue
        stocks_mlb = stocks_klb / 1000.0
        rows.append({
            "data_year": data_y,
            "data_month": data_m,
            "period_label": f"{data_y:04d}-{data_m:02d}",
            "pork_stocks_mlb": stocks_mlb,
        })
    rows.sort(key=lambda r: (r["data_year"], r["data_month"]))
    return rows


def attach_5yr_stats(rows: list[dict]) -> None:
    """Add same-month 5-year min / mean / sigma in-place, for the build log only
    (they are not written to the CSV; the gt step recomputes them from it).

    For row with (year, month), the reference window is the rows whose
    `data_month == month` and `data_year < year`, taking up to the 5
    most recent such rows (i.e. the prior 5 calendar years' same-month
    values).
    """
    rows_by_month: dict[int, list[dict]] = {}
    for r in rows:
        rows_by_month.setdefault(r["data_month"], []).append(r)
    for r in rows:
        m = r["data_month"]; y = r["data_year"]
        siblings = [s for s in rows_by_month[m] if s["data_year"] < y]
        siblings.sort(key=lambda s: s["data_year"])
        ref = siblings[-5:]
        values = [s["pork_stocks_mlb"] for s in ref]
        if values:
            mn = min(values)
            mean = statistics.fmean(values)
            sigma = statistics.pstdev(values) if len(values) >= 2 else 0.0
        else:
            mn = float("nan"); mean = float("nan"); sigma = float("nan")
        r["same_month_5yr_min"] = mn
        r["same_month_5yr_mean"] = mean
        r["same_month_5yr_sigma"] = sigma
        r["_n_ref"] = len(values)
        if values and len(values) >= 2:
            r["derived_band"] = classify_band(r["pork_stocks_mlb"], mn, mean, sigma)
        else:
            r["derived_band"] = "insufficient_history"


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True, help="YYYY-MM (data month)")
    ap.add_argument("--instance-end",   required=True, help="YYYY-MM (data month)")
    args = ap.parse_args()

    start = parse_instance_label(args.instance_start)
    end   = parse_instance_label(args.instance_end)

    rows = harvest_pork_history()
    if not rows:
        print("[err] no rows harvested from PDFs", file=sys.stderr)
        return 1
    attach_5yr_stats(rows)
    print(f"[info] harvested {len(rows)} monthly rows "
          f"({rows[0]['period_label']}..{rows[-1]['period_label']})")

    INSTANCES.mkdir(parents=True, exist_ok=True)
    n = 0
    for (yr, mo) in enumerate_months(start, end):
        key = (yr, mo)
        if not any((r["data_year"], r["data_month"]) == key for r in rows):
            print(f"[warn] {yr:04d}-{mo:02d} not parsed from any PDF",
                  file=sys.stderr); continue
        cum = [r for r in rows if (r["data_year"], r["data_month"]) <= key]
        folder = INSTANCES / month_to_folder(yr, mo)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "timeseries.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(CSV_COLUMNS)
            for r in cum:
                w.writerow([
                    r["data_year"], r["data_month"], r["period_label"],
                    f"{r['pork_stocks_mlb']:.3f}",
                ])
        last = cum[-1]
        n += 1
        print(f"[ok] {folder.name}/timeseries.csv ({len(cum)} rows; latest "
              f"{last['period_label']} stocks={last['pork_stocks_mlb']:.1f} mlb "
              f"5yr min={last['same_month_5yr_min']:.1f} "
              f"mean={last['same_month_5yr_mean']:.1f} "
              f"sigma={last['same_month_5yr_sigma']:.1f})")
    print(f"[done] wrote {n} per-instance CSVs")
    return 0


# --- step: gt ------------------------------------------------------------
#: Same-month rows the reference window needs; fewer and the band is undefined.
WINDOW_YEARS = 5


def reference_window(csv_path: Path, yr: int, mo: int) -> tuple[dict, list[dict]]:
    """The instance's own row and its reference window, both read from timeseries.csv.

    The window is the {WINDOW_YEARS} most recent earlier rows for the same
    calendar month, the same selection attach_5yr_stats() makes.
    """
    with csv_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    current = next(r for r in rows if r["period_label"] == f"{yr:04d}-{mo:02d}")
    earlier = [r for r in rows
               if int(r["data_month"]) == mo and int(r["data_year"]) < yr]
    earlier.sort(key=lambda r: int(r["data_year"]))
    return current, earlier[-WINDOW_YEARS:]


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    start = parse_instance_label(args.instance_start)
    end   = parse_instance_label(args.instance_end)
    n = 0
    failed: list[str] = []
    for (yr, mo) in enumerate_months(start, end):
        folder = INSTANCES / month_to_folder(yr, mo)
        csv_path = folder / "timeseries.csv"
        if not csv_path.exists():
            print(f"[skip] {folder.name}", file=sys.stderr); continue
        period_label = f"{yr:04d}-{mo:02d}"
        # Derive the answer from exactly the rows the agent sees, so the
        # instance is answerable from its own CSV by construction. Without a
        # full reference window it is not answerable at all: build nothing.
        row, window = reference_window(csv_path, yr, mo)
        if len(window) < WINDOW_YEARS:
            print(f"[fail] {period_label}: timeseries.csv has only {len(window)} "
                  f"earlier {month_label(yr, mo)[:-5]} rows, need {WINDOW_YEARS}",
                  file=sys.stderr)
            for stale in ("ground_truth.json", "gt_evidence.md"):
                (folder / stale).unlink(missing_ok=True)
            failed.append(period_label); continue
        values = [float(r["pork_stocks_mlb"]) for r in window]
        stocks = float(row["pork_stocks_mlb"])
        mn = min(values)
        mean = statistics.fmean(values)
        sigma = statistics.pstdev(values)
        band = classify_band(stocks, mn, mean, sigma)

        (folder / "ground_truth.json").write_text(
            json.dumps({"pork_storage_band": band,
                        "report": ""},
                       indent=2) + "\n", encoding="utf-8")

        evidence = (
            "# Ground-truth evidence -- USDA Cold Storage Total pork band\n\n"
            f"## Instance data month: {month_label(yr, mo)} ({period_label})\n\n"
            f"- **US Total pork stocks** = **{stocks:.1f}** million pounds "
            f"(end of {month_label(yr, mo)})\n"
            f"- **Same-month 5-year reference window** (prior 5 calendar years' "
            f"{month_label(yr, mo)[:-5]}'s):\n"
            f"  - min  = {mn:.1f} mlb\n"
            f"  - mean = {mean:.1f} mlb\n"
            f"  - sigma = {sigma:.1f} mlb\n"
            f"  - mean - 0.5*sigma = {mean - 0.5*sigma:.1f} mlb\n"
            f"  - mean + 0.5*sigma = {mean + 0.5*sigma:.1f} mlb\n"
            f"- Source rows in `timeseries.csv`: `period_label={period_label}` "
            f"and window `{', '.join(r['period_label'] for r in window)}`\n"
            f"- Applied per-month rule:\n"
            f"  - stocks <  min                    -> `tight`\n"
            f"  - stocks <  mean - 0.5*sigma       -> `low`\n"
            f"  - stocks <  mean + 0.5*sigma       -> `normal`\n"
            f"  - else                              -> `heavy`\n"
            f"- **Derived band: `{band}`**\n\n"
            "## Traceability\n\n"
            "- Source release for this data month: USDA NASS Cold Storage PDF "
            "(cost<MMYY>.pdf with MMYY = release month following this data "
            "month) on the esmis landing page at "
            f"{LANDING_BASE}\n"
        )
        (folder / "gt_evidence.md").write_text(evidence, encoding="utf-8")
        n += 1
        print(f"[ok] {folder.name}: stocks={stocks:.1f} -> {band}")
    print(f"[done] wrote {n} ground-truth files")
    if failed:
        print(f"[fail] {len(failed)} instance(s) not answerable from timeseries.csv: "
              f"{', '.join(failed)}", file=sys.stderr)
        return 1
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
