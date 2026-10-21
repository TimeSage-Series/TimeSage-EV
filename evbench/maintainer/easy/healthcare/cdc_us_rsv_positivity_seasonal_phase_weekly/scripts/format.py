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
import datetime as dt
from _common import (TS_SOURCE, INSTANCES, DATASET_ID, DATASET_NAME, PATHOGEN,
                     UNIT, PAGE_URL, classify, same_week_baseline,
                     week_label, iter_weeks, _quartiles)  # noqa


# --- step: timeseries ----------------------------------------------------

COLS = ["week_ending", "iso_week", "percent_pos"]


def load_all_rows() -> list[dict]:
    """Load every timeseries_source/*.json and return as list of rows
    sorted by week_ending ascending."""
    rows = []
    for p in sorted(TS_SOURCE.glob("*.json")):
        d = json.loads(p.read_text())
        rows.append({
            "week_ending": d["week_ending"],
            "iso_week":    d["iso_week"],
            "percent_pos": float(d["percent_pos"]),
        })
    rows.sort(key=lambda r: r["week_ending"])
    return rows


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    all_rows = load_all_rows()

    for y, w, sat in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(sat)
        target_idx = None
        for i, r in enumerate(all_rows):
            if r["iso_week"] == label:
                target_idx = i; break
        if target_idx is None:
            print(f"[skip] {label}: no source row", flush=True); continue
        window = all_rows[: target_idx + 1]
        out = INSTANCES / label
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "timeseries.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=COLS)
            wr.writeheader()
            for r in window:
                wr.writerow({
                    "week_ending": r["week_ending"],
                    "iso_week":    r["iso_week"],
                    "percent_pos": f"{r['percent_pos']:.2f}",
                })
        print(f"[ok]  {label}: cumulative {len(window)} weeks; latest "
              f"pp={all_rows[target_idx]['percent_pos']:.2f}", flush=True)


# --- step: gt ------------------------------------------------------------
THRESHOLD_TEXT = (
    "- `off_season` : percent_pos <  same-week 5yr p25\n"
    "- `active`     : same-week 5yr p25 <= percent_pos <  same-week 5yr p50\n"
    "- `elevated`   : same-week 5yr p50 <= percent_pos <  same-week 5yr p75\n"
    "- `peak`       : percent_pos >= same-week 5yr p75"
)


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    failed: list[str] = []
    for y, w, sat in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(sat)
        ts_path = TS_SOURCE / f"{label}.json"
        out_dir = INSTANCES / label
        if not ts_path.exists() or not out_dir.exists():
            print(f"[skip] {label}", flush=True); continue
        d = json.loads(ts_path.read_text())
        # Derive the answer from exactly the rows the agent sees: the latest
        # row of timeseries.csv and, for the baseline, the CSV's own history.
        # Without enough same-week history the instance is unanswerable:
        # build nothing for it.
        with open(out_dir / "timeseries.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        row = rows[-1]
        pp = float(row["percent_pos"])
        iso = dt.date.fromisoformat(row["week_ending"]).isocalendar()
        baseline = same_week_baseline(rows, iso.week, iso.year)
        if len(baseline) < 3:
            print(f"[fail] {label}: insufficient same-week history in "
                  f"timeseries.csv ({len(baseline)} years)", file=sys.stderr, flush=True)
            for stale in ("ground_truth.json", "gt_evidence.md"):
                (out_dir / stale).unlink(missing_ok=True)
            failed.append(label); continue
        p25, p50, p75 = _quartiles(baseline)
        phase = classify(pp, baseline)

        gt = {"rsv_phase": phase, "report": ""}
        (out_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))

        baseline_repr = ", ".join(f"{v:.2f}" for v in baseline)
        ev = (
            f"# Evidence — {label}\n\n"
            f"Source: CDC dataset `{DATASET_ID}` — {DATASET_NAME}.\n"
            f"Dataset page: {PAGE_URL}\n"
            f"Pathogen filter: `{PATHOGEN}`; level: `National`; subtype: `Combined Type`.\n\n"
            f"## Sampling rule\n\n"
            f"CDC publishes a Saturday MMWR-week-ending percent_pos (NAAT\n"
            f"percent positive) for the RSV national aggregate via the\n"
            f"NREVSS dashboard. We use the published Saturday date as\n"
            f"the row date in `timeseries.csv`.\n\n"
            f"## Threshold cascade ({UNIT})\n\n"
            f"{THRESHOLD_TEXT}\n\n"
            f"The same-week 5-year baseline uses percent_pos values for\n"
            f"the same MMWR week number from the five years immediately\n"
            f"preceding the target year; quartiles are computed with\n"
            f"`statistics.quantiles(method='exclusive')` (equivalent to\n"
            f"the default `n=4` in CPython's `statistics` module).\n\n"
            f"## Per-answer-field citation\n\n"
            f"- **rsv_phase**            -> `{phase}` "
            f"(percent_pos value `{pp:.2f}` versus 5-yr same-week p25 `{p25:.2f}`, "
            f"p50 `{p50:.2f}`, p75 `{p75:.2f}`)\n"
            f"- Source rows in `timeseries.csv`: `week_ending={row['week_ending']}` "
            f"(latest row) and the same-week rows of the five prior years\n\n"
            f"## 5-year same-MMWR-week baseline values\n\n"
            f"Baseline (sorted by year ascending): [{baseline_repr}]\n\n"
            f"## Verbatim CDC row\n\n"
            f"```json\n{json.dumps(d['raw_row'], indent=2)}\n```\n"
        )
        (out_dir / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: pp={pp:.2f} (p25={p25:.2f},p50={p50:.2f},"
              f"p75={p75:.2f}) -> {phase}", flush=True)
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
