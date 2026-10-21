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
from _common import TS_SOURCE, INSTANCES, month_label, iter_months  # noqa
from _common import (TS_SOURCE, INSTANCES, SERIES_ID, classify,
                     month_label, iter_months)  # noqa


# --- step: timeseries ----------------------------------------------------

COLS = ["observation_date", "month_label", "sahm_value"]


def load_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in sorted(TS_SOURCE.glob("*.json")):
        d = json.loads(p.read_text())
        out[d["month_label"]] = {
            "observation_date": d["observation_date"],
            "month_label":      d["month_label"],
            "sahm_value":       f"{float(d['value']):.2f}",
        }
    return out


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    all_rows = load_all()
    ordered = sorted(all_rows.keys())

    for y, m, _ in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        if label not in all_rows:
            print(f"[skip] {label}: no raw row published", flush=True)
            continue
        idx = ordered.index(label)
        window = ordered[: idx + 1]
        out = INSTANCES / label
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "timeseries.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=COLS)
            wr.writeheader()
            for lab in window:
                wr.writerow(all_rows[lab])
        latest = all_rows[label]
        print(f"[ok]  {label}: cumulative {len(window)} months; "
              f"latest value={latest['sahm_value']}",
              flush=True)


# --- step: gt ------------------------------------------------------------
def latest_csv_row(csv_path: Path) -> dict:
    """The last row of an instance's timeseries.csv: the value the agent answers from."""
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))[-1]


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    for y, m, _ in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        ts_path = TS_SOURCE / f"{label}.json"
        out_dir = INSTANCES / label
        if not ts_path.exists() or not out_dir.exists():
            print(f"[skip] {label}", flush=True)
            continue
        d = json.loads(ts_path.read_text())
        # Derive the answer from exactly the row the agent sees (the latest row
        # of timeseries.csv); the source row is kept in the evidence as provenance.
        row = latest_csv_row(out_dir / "timeseries.csv")
        value = float(row["sahm_value"])
        cat = classify(value)
        if cat != d["category"]:
            print(f"[warn] {label}: stored category {d['category']} != "
                  f"CSV-derived {cat}; using CSV-derived", flush=True)
        obs_date = d["observation_date"]
        gt = {
            "category":   cat,
            "report": "",
        }
        (out_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        ev = (
            f"# Evidence — {label}\n\n"
            f"Source: Federal Reserve Bank of St. Louis (FRED), series "
            f"`{SERIES_ID}` (Sahm Rule Recession Indicator).\n\n"
            f"CSV endpoint: "
            f"`https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES_ID}`\n\n"
            f"## Per-answer-field citation\n\n"
            f"- **category** -> `{cat}` (Sahm-rule bucket of the "
            f"`{SERIES_ID}` value `{value:.2f}` at observation_date "
            f"`{obs_date}`; thresholds: <0.30 normal, 0.30-<0.50 "
            f"elevated_no_signal, >=0.50 recession_signal)\n"
            f"- Source row in `timeseries.csv`: `observation_date={row['observation_date']}` (latest row)\n\n"
            f"## Verbatim row\n\n"
            f"```json\n{json.dumps(d, indent=2)}\n```\n"
        )
        (out_dir / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: {cat} (value={value:.2f})", flush=True)

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
