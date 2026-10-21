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
from _common import (TS_SOURCE, INSTANCES, TARGET_SITE, TARGET_STATE,
                     PATHOGEN_TARGET, week_label, iter_weeks)  # noqa


# --- step: timeseries ----------------------------------------------------

COLS = ["week_end", "iso_week", "site_wval"]


def load_all() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in sorted(TS_SOURCE.glob("*.json")):
        d = json.loads(p.read_text())
        if not d["rows"]:
            continue
        r = d["rows"][0]
        out[d["iso_week"]] = {
            "week_end":           r["week_end"][:10],
            "iso_week":           d["iso_week"],
            "site_wval":          r.get("site_wval"),
        }
    return out


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    all_rows = load_all()
    ordered = sorted(all_rows.keys())

    for y, w, sat in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(sat)
        if label not in all_rows:
            print(f"[skip] {label}: no raw row published", flush=True); continue
        idx = ordered.index(label)
        window = ordered[: idx + 1]
        out = INSTANCES / label
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "timeseries.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=COLS)
            wr.writeheader()
            for lab in window:
                wr.writerow(all_rows[lab])
        print(f"[ok]  {label}: cumulative {len(window)} weeks; latest={all_rows[label]['site_wval']}",
              flush=True)


# --- step: gt ------------------------------------------------------------
#: Deadband on the signed week-over-week % change (environment/scoring.yaml).
WOW_DEADBAND_PCT = 10.0


def wow_direction(prev: float, cur: float) -> tuple[str, float | None]:
    """Direction tag and signed WoW %; `stable` when the prior week is zero
    (WoW % undefined). A missing prior week is handled by the caller."""
    if prev == 0:
        return "stable", None
    pct = (cur - prev) / prev * 100
    if pct > WOW_DEADBAND_PCT:
        return "rising", pct
    if pct < -WOW_DEADBAND_PCT:
        return "falling", pct
    return "stable", pct


def last_two_weeks(csv_path: Path) -> tuple[dict, dict | None]:
    """The latest row and the row exactly one week before it, from timeseries.csv."""
    with open(csv_path, newline="") as f:
        rows = list(csv.DictReader(f))
    cur = rows[-1]
    want = (dt.date.fromisoformat(cur["week_end"]) - dt.timedelta(days=7)).isoformat()
    prev = next((r for r in rows if r["week_end"] == want), None)
    return cur, prev


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    all_rows = load_all()
    failed: list[str] = []

    for y, w, sat in iter_weeks(args.instance_start, args.instance_end):
        label = week_label(sat)
        out_dir = INSTANCES / label
        if label not in all_rows or not out_dir.exists():
            print(f"[skip] {label}", flush=True); continue
        # Derive the answer from exactly the rows the agent sees. Without the
        # previous week's row there is no WoW change to classify, so the
        # instance is unanswerable: build nothing for it.
        cur_row, prev_row = last_two_weeks(out_dir / "timeseries.csv")
        if prev_row is None:
            print(f"[fail] {label}: timeseries.csv lacks the week before "
                  f"{cur_row['week_end']}", file=sys.stderr, flush=True)
            for stale in ("ground_truth.json", "gt_evidence.md"):
                (out_dir / stale).unlink(missing_ok=True)
            failed.append(label); continue
        cur = float(cur_row["site_wval"])
        prev = float(prev_row["site_wval"])
        direction, pct = wow_direction(prev, cur)

        gt = {"wow_direction": direction, "report": ""}
        (out_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2) + "\n")

        calc = (f"({cur:g} - {prev:g}) / {prev:g} = {pct:+.1f}% "
                f"vs prior week {prev_row['iso_week']} "
                f"(`timeseries.csv` rows {prev_row['week_end']} and "
                f"{cur_row['week_end']})")
        ev = (
            f"# Evidence — {label}\n\n"
            f"Source: CDC National Wastewater Surveillance System (NWSS), "
            f"dataset atcp-73re on data.cdc.gov; site `{TARGET_SITE}`, "
            f"pathogen `{PATHOGEN_TARGET}`.\n\n"
            f"## Per-answer-field citation\n\n"
            f"- **wow_direction** → `{direction}` — WoW % change in `site_wval`: "
            f"{calc}\n"
            f"- Rule: WoW% > +{WOW_DEADBAND_PCT:g} → `rising`; "
            f"WoW% < -{WOW_DEADBAND_PCT:g} → `falling`; otherwise `stable`.\n\n"
            f"## Rows\n\n"
            f"| week_end | iso_week | site_wval |\n|---|---|---|\n"
            + "".join(f"| {r['week_end']} | {r['iso_week']} | {r['site_wval']} |\n"
                      for r in (prev_row, cur_row))
        )
        (out_dir / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: {direction}", flush=True)
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
