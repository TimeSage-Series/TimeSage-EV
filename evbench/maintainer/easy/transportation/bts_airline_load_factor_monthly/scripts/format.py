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
from _common import INSTANCES, QUERY_MONTHS, SERIES_ID, TS_SOURCE
import json
from _common import INSTANCES, query_months


# --- step: timeseries ----------------------------------------------------


def load_observations(csv_path: Path) -> list[tuple[str, float | None]]:
    out: list[tuple[str, float | None]] = []
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        date_col = "observation_date" if "observation_date" in fieldnames else fieldnames[0]
        value_col = SERIES_ID if SERIES_ID in fieldnames else fieldnames[-1]
        for row in reader:
            d = row[date_col].strip()
            v = row[value_col].strip()
            if not d:
                continue
            month = d[:7]
            try:
                value: float | None = None if v in ("", ".") else float(v)
            except ValueError:
                value = None
            out.append((month, value))
    return out


def _step_timeseries() -> int:
    src = TS_SOURCE / "loadfactor.csv"
    if not src.exists():
        print(f"MISSING: {src} — run `download.py timeseries` first",
              file=sys.stderr)
        return 1
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()
    months = query_months(args.instance_start, args.instance_end)
    obs = load_observations(src)
    INSTANCES.mkdir(parents=True, exist_ok=True)
    for q in months:
        # No instance for a month the source has not published yet.
        if not any(month == q for month, _ in obs):
            continue
        inst_dir = INSTANCES / q
        inst_dir.mkdir(parents=True, exist_ok=True)
        ts_path = inst_dir / "timeseries.csv"
        with ts_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["data_month", "load_factor"])
            for month, value in obs:
                if month > q:
                    continue
                value_s = f"{value:.1f}" if value is not None else ""
                w.writerow([month, value_s])
        print(f"wrote {ts_path}", file=sys.stderr)
    return 0


# --- step: gt ------------------------------------------------------------
def _f(v):
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()
    months = query_months(args.instance_start, args.instance_end)
    if not INSTANCES.exists():
        print("Run `format.py timeseries` first", file=sys.stderr)
        return 1

    for q in months:
        inst_dir = INSTANCES / q
        ts_path = inst_dir / "timeseries.csv"
        if not ts_path.exists():
            print(f"MISSING ts: {ts_path}", file=sys.stderr)
            continue

        with ts_path.open() as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
        if not rows:
            print(f"EMPTY ts: {ts_path}", file=sys.stderr)
            continue

        latest = rows[-1]
        latest_v = _f(latest[1])
        # Trailing-12 (inclusive of latest) window: needs at least 11 priors.
        is_high = False
        prior11 = rows[-12:-1]  # may be fewer if rows < 12.
        if latest_v is not None and len(prior11) >= 11:
            prior_vals = [_f(r[1]) for r in prior11]
            if all(v is not None and latest_v > v for v in prior_vals):
                is_high = True

        gt = {
            "is_year_high_load_factor": is_high,
            "report": "",
        }
        (inst_dir / "ground_truth.json").write_text(
            json.dumps(gt, indent=2) + "\n"
        )

        ev_lines = [
            f"# Ground-truth evidence — month {q}",
            "",
            f"U.S. system-wide passenger load factor for **{latest[0]}**: "
            f"**{latest_v:.1f}%**" if latest_v is not None else
            f"U.S. system-wide passenger load factor for **{latest[0]}**: (no value)",
            "",
            f"Trailing-12-month maximum? **{'TRUE' if is_high else 'FALSE'}**.",
            "",
            "## Source",
            "",
            "- FRED series `LOADFACTOR` (BTS T-100 system-wide passenger "
            "load factor mirrored on FRED); raw CSV in "
            "`gt_source/loadfactor.csv`.",
            f"- Window: rows for the latest month ({latest[0]}) and the 11 "
            "immediately preceding monthly rows in "
            f"`instances/{q}/timeseries.csv`.",
            "",
            "## Trailing-12 window",
            "",
            "| data_month | load_factor (%) |",
            "|---|---|",
        ]
        for r in rows[-12:]:
            v = _f(r[1])
            mark = "  ← latest" if r is rows[-1] else ""
            v_s = f"{v:.1f}" if v is not None else "—"
            ev_lines.append(f"| {r[0]} | {v_s}{mark} |")
        (inst_dir / "gt_evidence.md").write_text("\n".join(ev_lines) + "\n")

        manifest = {
            "scenario_id": "bts_airline_load_factor_monthly",
            "as_of_data_month": latest[0],
            "accessible_artifacts": [
                {
                    "path": "gt_source/loadfactor.csv",
                    "kind": "csv",
                    "description": "FRED LOADFACTOR full-history CSV "
                                   "(BTS system-wide passenger load factor)",
                }
            ],
            "note": "The same monthly CSV that feeds the timeseries also "
                    "carries the GT (the load factor values). The trailing-12 "
                    "maximum is computed from the last 12 rows of "
                    "timeseries.csv.",
        }
        (inst_dir / "visible_reports.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )

        print(f"wrote GT for {q}: is_year_high={is_high}",
              file=sys.stderr)
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
