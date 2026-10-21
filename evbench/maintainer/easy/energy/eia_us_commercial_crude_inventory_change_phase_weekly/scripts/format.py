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
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, INSTANCES, week_label, iter_weeks  # noqa
from _common import (TS_SOURCE, INSTANCES, SERIES_ID, SERIES_LONG_NAME,
                     UNIT_CHANGE, PAGE_URL, classify, week_label,
                     iter_weeks)  # noqa


# --- step: timeseries ----------------------------------------------------

# Levels only. The week-over-week change is deliberately left out: the phase
# is a deadband on it, so shipping it would turn the task into a column
# lookup. The agent has to difference the last two rows itself.
COLS = ["week_ending", "iso_week", "stocks_thousand_bbl"]


def load_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in sorted(TS_SOURCE.glob("*.json")):
        d = json.loads(p.read_text())
        out[d["iso_week"]] = {
            "week_ending":          d["week_ending"],
            "iso_week":             d["iso_week"],
            "stocks_thousand_bbl":  f"{float(d['stocks_thousand_bbl']):.0f}",
        }
    return out


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    all_rows = load_all()
    ordered = sorted(all_rows.keys())

    for y, w, friday in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(friday)
        if label not in all_rows:
            print(f"[skip] {label}", flush=True); continue
        idx = ordered.index(label)
        window = ordered[: idx + 1]
        out = INSTANCES / label
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "timeseries.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=COLS)
            wr.writeheader()
            for lab in window:
                wr.writerow(all_rows[lab])
        print(f"[ok]  {label}: cumulative {len(window)} weeks; latest "
              f"stocks={all_rows[label]['stocks_thousand_bbl']}kbbl", flush=True)


# --- step: gt ------------------------------------------------------------
THRESHOLD_TEXT = (
    "- `build` : change >= +0.5\n"
    "- `draw`  : change <= -0.5\n"
    "- `flat`  : -0.5 < change < +0.5"
)


def last_two_weeks(csv_path) -> tuple[dict, dict | None]:
    """The latest row and the row exactly one week before it, from timeseries.csv."""
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    cur = rows[-1]
    want = (dt.date.fromisoformat(cur["week_ending"]) - dt.timedelta(days=7)).isoformat()
    prev = next((r for r in rows if r["week_ending"] == want), None)
    return cur, prev


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    failed: list[str] = []
    for y, w, friday in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(friday)
        ts_path = TS_SOURCE / f"{label}.json"
        out_dir = INSTANCES / label
        if not ts_path.exists() or not out_dir.exists():
            print(f"[skip] {label}", flush=True); continue
        d = json.loads(ts_path.read_text())
        # Derive the answer from exactly the rows the agent sees, so the
        # instance is answerable from its own CSV by construction. Without the
        # prior week's row it is not answerable at all: build nothing for it.
        cur, prev = last_two_weeks(out_dir / "timeseries.csv")
        if prev is None:
            print(f"[fail] {label}: timeseries.csv lacks the week before "
                  f"{cur['week_ending']}", file=sys.stderr, flush=True)
            for stale in ("ground_truth.json", "gt_evidence.md"):
                (out_dir / stale).unlink(missing_ok=True)
            failed.append(label); continue
        wow = (int(cur["stocks_thousand_bbl"]) - int(prev["stocks_thousand_bbl"])) / 1000
        cat = classify(wow)
        if cat != d["crude_inventory_phase"]:
            print(f"[warn] {label}: stored {d['crude_inventory_phase']} != "
                  f"CSV-derived {cat}; using CSV-derived", flush=True)

        as_of = d["week_ending"]

        gt = {"crude_inventory_phase": cat, "report": ""}
        (out_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))

        ev = (
            f"# Evidence — {label}\n\n"
            f"Source: U.S. Energy Information Administration, series "
            f"`{SERIES_ID}` — {SERIES_LONG_NAME}.\n"
            f"Dashboard page: {PAGE_URL}\n\n"
            f"## Sampling rule\n\n"
            f"EIA publishes a Friday week-ending US commercial crude\n"
            f"stocks total (in thousand barrels, excluding the Strategic\n"
            f"Petroleum Reserve) as part of the Weekly Petroleum Status\n"
            f"Report (Wednesday release for the prior Friday). The week\n"
            f"over-week change in MILLION barrels is computed as\n"
            f"`(stocks_thousand_bbl_current - stocks_thousand_bbl_prior) / 1000`.\n\n"
            f"## Threshold cascade ({UNIT_CHANGE})\n\n"
            f"{THRESHOLD_TEXT}\n\n"
            f"## Per-answer-field citation\n\n"
            f"- **crude_inventory_phase** -> `{cat}` "
            f"(week-over-week change `{wow:+.3f}` MMbbl = "
            f"({cur['stocks_thousand_bbl']} - {prev['stocks_thousand_bbl']}) / 1000 "
            f"from `timeseries.csv` rows `week_ending={cur['week_ending']}` and "
            f"`week_ending={prev['week_ending']}` — threshold bucket per cascade above)\n"
            f"- **as_of_week_ending**     -> `{as_of}` "
            f"(Friday week-ending date of EIA series {SERIES_ID})\n\n"
            f"## Verbatim EIA row\n\n"
            f"```json\n{json.dumps(d['raw_row'], indent=2)}\n```\n"
        )
        (out_dir / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: wow={wow:+.3f}MMbbl -> {cat}", flush=True)
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
