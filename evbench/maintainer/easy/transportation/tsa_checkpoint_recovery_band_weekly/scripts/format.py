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
from _common import (TS_SOURCE, INSTANCES, PUBLISHER, SOURCE_LONG_NAME,
                     TSA_BASE_URL, classify, week_label, iter_weeks)  # noqa


# --- step: timeseries ----------------------------------------------------

# Counts only. The recovery ratio is deliberately left out: the band is a cut
# on it, so shipping it would turn the task into a column lookup. The agent
# divides throughput by baseline_2019 itself.
COLS = [
    "week_ending", "iso_week", "throughput", "baseline_2019",
]


def load_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in sorted(TS_SOURCE.glob("*.json")):
        d = json.loads(p.read_text())
        out[d["iso_week"]] = {
            "week_ending":   d["week_ending"],
            "iso_week":      d["iso_week"],
            "throughput":    str(int(d["throughput"])),
            "baseline_2019": str(int(d["baseline_2019"])),
        }
    return out


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    all_rows = load_all()
    ordered = sorted(all_rows.keys())

    for y, w, sunday in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(sunday)
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
              f"throughput={all_rows[label]['throughput']} "
              f"baseline_2019={all_rows[label]['baseline_2019']}", flush=True)


# --- step: gt ------------------------------------------------------------
THRESHOLD_TEXT = (
    "- `well_below`   : recovery <  0.75\n"
    "- `still_below`  : 0.75 <= recovery <  0.95\n"
    "- `approaching`  : 0.95 <= recovery <  1.05\n"
    "- `recovered`    : recovery >= 1.05"
)


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    for y, w, sunday in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(sunday)
        ts_path = TS_SOURCE / f"{label}.json"
        out_dir = INSTANCES / label
        if not ts_path.exists() or not out_dir.exists():
            print(f"[skip] {label}", flush=True); continue
        d = json.loads(ts_path.read_text())
        # Derive the answer from exactly the row the agent sees.
        with open(out_dir / "timeseries.csv", newline="") as f:
            row = list(csv.DictReader(f))[-1]
        throughput = int(row["throughput"])
        baseline = int(row["baseline_2019"])
        recovery = throughput / baseline
        cat = classify(recovery)
        if cat != d["recovery_band"]:
            print(f"[warn] {label}: stored {d['recovery_band']} != "
                  f"CSV-derived {cat}; using CSV-derived", flush=True)

        as_of = d["week_ending"]

        gt = {"recovery_band": cat, "report": ""}
        (out_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))

        ev = (
            f"# Evidence — {label}\n\n"
            f"Source: {PUBLISHER} — {SOURCE_LONG_NAME} (daily TSA "
            f"checkpoint counts).\n"
            f"Dashboard page (current year): {TSA_BASE_URL}\n"
            f"Archive ({y}): {TSA_BASE_URL}/{y}\n"
            f"Baseline (2019): {TSA_BASE_URL}/2019\n\n"
            f"## Sampling rule\n\n"
            f"Each ISO week's Monday-Sunday daily counts are summed to\n"
            f"produce that week's `throughput`. The same ISO-week-of-year\n"
            f"throughput from calendar year 2019 is the recovery\n"
            f"baseline. The recovery ratio is `throughput / baseline_2019`. The\n"
            f"`as_of_week_ending` is the Sunday of the ISO week.\n\n"
            f"## Threshold cascade\n\n"
            f"{THRESHOLD_TEXT}\n\n"
            f"## Per-answer-field citation\n\n"
            f"- **recovery_band**     -> `{cat}` "
            f"(throughput={throughput} baseline_2019={baseline} "
            f"recovery = throughput / baseline_2019 = {recovery:.4f} from the latest `timeseries.csv` row, threshold bucket per cascade above)\n"
            f"- **as_of_week_ending** -> `{as_of}` (Sunday of ISO week {label})\n\n"
            f"## Verbatim TSA daily rows\n\n"
            f"```json\n{json.dumps(d['raw_row'], indent=2)}\n```\n"
        )
        (out_dir / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: recovery={recovery:.4f} -> {cat}", flush=True)

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
