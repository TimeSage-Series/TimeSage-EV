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
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    TS_SOURCE, INSTANCES, classify_phase,
    mmyy_to_release_month, release_to_data_month,
    month_to_folder,
)
from _pdf_parser import parse_layers  # noqa: E402
import json
from _common import (  # noqa: E402
    INSTANCES, classify_phase, LANDING_BASE,
    month_to_folder, month_label,
)


# --- step: timeseries ----------------------------------------------------

# One row per data month, as known when the instance's report came out:
# the first-published level, and the revised level once a later report has
# restated it (empty until then). Neither the signed YoY % nor a prior-year
# column is shipped: the phase is a deadband on the YoY %, so the agent has to
# find the same month a year earlier and compute it.
CSV_COLUMNS = [
    "data_year", "data_month", "period_label",
    "layers_klb", "layers_revised_klb",
]


def parse_instance_label(s: str) -> tuple[int, int]:
    return int(s[:4]), int(s[5:])


def enumerate_months(start, end):
    y, m = start; ey, em = end
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12: m = 1; y += 1


def harvest_layers_history() -> list[dict]:
    rows = []
    for pdf in sorted(TS_SOURCE.glob("ckeg*.pdf")):
        mmyy = pdf.stem.replace("ckeg", "")
        try:
            rel_y, rel_m = mmyy_to_release_month(mmyy)
        except ValueError:
            print(f"[warn] bad filename {pdf.name}", file=sys.stderr); continue
        data_y, data_m = release_to_data_month(rel_y, rel_m)
        try:
            prior_klb, current_klb = parse_layers(pdf, data_y, data_m)
        except Exception as e:
            print(f"[warn] parse failed {pdf.name}: {e}", file=sys.stderr); continue
        if prior_klb <= 0:
            print(f"[warn] non-positive prior in {pdf.name}", file=sys.stderr); continue
        yoy = (current_klb - prior_klb) / prior_klb * 100.0
        rows.append({
            "data_year": data_y,
            "data_month": data_m,
            "period_label": f"{data_y:04d}-{data_m:02d}",
            "layers_current_klb": current_klb,
            "layers_prior_year_klb": prior_klb,
            "yoy_pct": yoy,
        })
    rows.sort(key=lambda r: (r["data_year"], r["data_month"]))
    return rows


def vintage_series(rows: list[dict], as_of: tuple[int, int]
                   ) -> list[tuple[tuple[int, int], Optional[int], Optional[int]]]:
    """(data month, first-published level, revised level) as of the report for `as_of`.

    The report for data month D publishes D for the first time and restates
    D minus one year (its prior-year column), usually revised. The revised
    level is None until such a restatement exists. Reports for data months
    after `as_of` are never used, so nothing from after the cutoff leaks in.
    """
    start = (rows[0]["data_year"], rows[0]["data_month"])
    first: dict[tuple[int, int], int] = {}
    revised: dict[tuple[int, int], int] = {}
    for r in rows:
        d = (r["data_year"], r["data_month"])
        if d > as_of:
            break
        first[d] = r["layers_current_klb"]
        prior = (d[0] - 1, d[1])
        if prior >= start:      # keep the history window where it starts
            revised[prior] = r["layers_prior_year_klb"]
    return [(d, first.get(d), revised.get(d)) for d in sorted(first.keys() | revised.keys())]


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True, help="YYYY-MM (data month)")
    ap.add_argument("--instance-end",   required=True, help="YYYY-MM (data month)")
    args = ap.parse_args()

    start = parse_instance_label(args.instance_start)
    end   = parse_instance_label(args.instance_end)

    rows = harvest_layers_history()
    if not rows:
        print("[err] no rows harvested from PDFs", file=sys.stderr); return 1
    print(f"[info] harvested {len(rows)} monthly rows "
          f"({rows[0]['period_label']}..{rows[-1]['period_label']})")

    INSTANCES.mkdir(parents=True, exist_ok=True)
    n = 0
    for (yr, mo) in enumerate_months(start, end):
        key = (yr, mo)
        if not any((r["data_year"], r["data_month"]) == key for r in rows):
            print(f"[warn] {yr:04d}-{mo:02d} not parsed", file=sys.stderr); continue
        series = vintage_series(rows, key)
        folder = INSTANCES / month_to_folder(yr, mo)
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "timeseries.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(CSV_COLUMNS)
            for (dy, dm), first, revised in series:
                w.writerow([dy, dm, f"{dy:04d}-{dm:02d}",
                            "" if first is None else first,
                            "" if revised is None else revised])
        last = next(r for r in rows if (r["data_year"], r["data_month"]) == key)
        n += 1
        print(f"[ok] {folder.name}/timeseries.csv ({len(series)} rows; latest "
              f"{last['period_label']} curr={last['layers_current_klb']} "
              f"prior={last['layers_prior_year_klb']} "
              f"yoy={last['yoy_pct']:+.2f}%)")
    print(f"[done] wrote {n} per-instance CSVs")
    return 0


# --- step: gt ------------------------------------------------------------
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
        prior_label = f"{yr - 1:04d}-{mo:02d}"
        # Derive the answer from exactly the rows the agent sees, so the
        # instance is answerable from its own CSV by construction. Without the
        # prior-year row it is not answerable at all: build nothing for it.
        with csv_path.open(encoding="utf-8") as fh:
            by_period = {r["period_label"]: r for r in csv.DictReader(fh)}
        if period_label not in by_period or prior_label not in by_period:
            print(f"[fail] {period_label}: timeseries.csv lacks "
                  f"{period_label} or {prior_label}", file=sys.stderr)
            for stale in ("ground_truth.json", "gt_evidence.md"):
                (folder / stale).unlink(missing_ok=True)
            failed.append(period_label); continue
        # The comparison uses each month's latest known level: revised when a
        # restatement exists (always, for the prior-year row), else first-published.
        cur_row, prior_row = by_period[period_label], by_period[prior_label]
        current = float(cur_row["layers_revised_klb"] or cur_row["layers_klb"])
        prior_col = "layers_revised_klb" if prior_row["layers_revised_klb"] else "layers_klb"
        prior = float(prior_row[prior_col])
        yoy = (current - prior) / prior * 100.0
        phase = classify_phase(yoy)

        (folder / "ground_truth.json").write_text(
            json.dumps({"layer_flock_yoy_phase": phase,
                        "report": ""},
                       indent=2) + "\n", encoding="utf-8")

        evidence = (
            "# Ground-truth evidence -- USDA Chickens & Eggs layer flock YoY\n\n"
            f"## Instance data month: {month_label(yr, mo)} ({period_label})\n\n"
            f"- **Total layers, 1,000 head**:\n"
            f"  - {month_label(yr, mo)}: **{current:.0f}** (`layers_klb`, first published)\n"
            f"  - {month_label(yr - 1, mo)}: **{prior:.0f}** (`{prior_col}`)\n"
            f"- Signed YoY% = (current - prior) / prior * 100 = "
            f"**{yoy:+.3f}%**\n"
            f"- Source rows in `timeseries.csv`: `period_label={period_label}` "
            f"and `period_label={prior_label}`\n"
            f"- Applied per-month rule:\n"
            f"  - YoY% >  +0.5 -> `expansion`\n"
            f"  - YoY% <  -0.5 -> `contraction`\n"
            f"  - otherwise    -> `steady`\n"
            f"- **Derived phase: `{phase}`**\n\n"
            "## Traceability\n\n"
            "- Source release for this data month: USDA NASS Chickens and "
            "Eggs PDF (ckeg<MMYY>.pdf with MMYY = release month following "
            "this data month) on the esmis landing page at "
            f"{LANDING_BASE}\n"
            "- Extracted from the 'Layers on Hand and Eggs Produced by "
            "Type and Molt -- United States' table, 'Layers during "
            f"{month_label(yr, mo).split()[0]} / Total layers' row.\n"
        )
        (folder / "gt_evidence.md").write_text(evidence, encoding="utf-8")
        n += 1
        print(f"[ok] {folder.name}: yoy={yoy:+.2f}% -> {phase}")
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
