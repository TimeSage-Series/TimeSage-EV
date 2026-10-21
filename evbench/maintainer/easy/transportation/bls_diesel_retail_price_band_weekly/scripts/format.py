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
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, INSTANCES, week_label, iter_weeks  # noqa
from _common import (TS_SOURCE, INSTANCES, SERIES_ID, SERIES_LONG_NAME,
                     PRICE_UNIT, PAGE_URL, classify,
                     CHEAP_UPPER, NORMAL_UPPER, ELEVATED_UPPER,
                     week_label, iter_weeks)  # noqa


# --- step: timeseries ----------------------------------------------------

COLS = ["observation_date", "iso_week", "price_usd_per_gal"]


def load_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in sorted(TS_SOURCE.glob("*.json")):
        d = json.loads(p.read_text())
        out[d["iso_week"]] = {
            "observation_date":   d["observation_date"],
            "iso_week":           d["iso_week"],
            "price_usd_per_gal":  f"{float(d['price_usd_per_gal']):.3f}",
        }
    return out


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    all_rows = load_all()
    ordered = sorted(all_rows.keys())

    for y, w, monday in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(monday)
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
              f"${all_rows[label]['price_usd_per_gal']}/gal", flush=True)


# --- step: gt ------------------------------------------------------------
THRESHOLD_TEXT = (
    f"- `cheap`    : price <  ${CHEAP_UPPER:.2f}\n"
    f"- `normal`   : ${CHEAP_UPPER:.2f} <= price <  ${NORMAL_UPPER:.2f}\n"
    f"- `elevated` : ${NORMAL_UPPER:.2f} <= price <  ${ELEVATED_UPPER:.2f}\n"
    f"- `extreme`  : price >= ${ELEVATED_UPPER:.2f}"
)


def latest_csv_row(csv_path: Path) -> dict:
    """The last row of an instance's timeseries.csv: the value the agent answers from."""
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))[-1]


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    for y, w, monday in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(monday)
        ts_path = TS_SOURCE / f"{label}.json"
        out_dir = INSTANCES / label
        if not ts_path.exists() or not out_dir.exists():
            print(f"[skip] {label}", flush=True); continue
        d = json.loads(ts_path.read_text())
        # Derive the answer from exactly the row the agent sees (the latest row
        # of timeseries.csv); the source row is kept in the evidence as provenance.
        row = latest_csv_row(out_dir / "timeseries.csv")
        price = float(row["price_usd_per_gal"])
        cat = d["diesel_price_band"]
        rederived = classify(price)
        if rederived != cat:
            print(f"[warn] {label}: stored {cat} != reclassified {rederived}; "
                  f"using reclassified", flush=True)
            cat = rederived


        gt = {"diesel_price_band": cat, "report": ""}
        (out_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))

        ev = (
            f"# Evidence — {label}\n\n"
            f"Source: Federal Reserve Bank of St. Louis (FRED) series "
            f"`{SERIES_ID}` — {SERIES_LONG_NAME} ({PRICE_UNIT}); upstream "
            f"U.S. Energy Information Administration weekly retail-diesel "
            f"survey.\n"
            f"Public CSV: "
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES_ID}\n"
            f"Dashboard page: {PAGE_URL}\n\n"
            f"## Sampling rule\n\n"
            f"EIA publishes the national-average retail diesel pump price\n"
            f"every Monday for the prior Monday's survey week. FRED indexes\n"
            f"the row by that Monday observation_date. We use the published\n"
            f"observation_date as the row date in `timeseries.csv`.\n\n"
            f"## Threshold cascade ({PRICE_UNIT})\n\n"
            f"{THRESHOLD_TEXT}\n\n"
            f"## Per-answer-field citation\n\n"
            f"- **diesel_price_band**  -> `{cat}` "
            f"(price = ${price:.3f} {PRICE_UNIT}, threshold bucket per cascade above)\n"
            f"- Source row in `timeseries.csv`: `observation_date={row['observation_date']}` (latest row)\n\n"
            f"## Verbatim FRED row\n\n"
            f"```json\n{json.dumps(d['raw_row'], indent=2)}\n```\n"
        )
        (out_dir / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: price=${price:.3f}/gal -> {cat}", flush=True)

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
