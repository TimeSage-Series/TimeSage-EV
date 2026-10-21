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
from _common import TS_SOURCE, INSTANCES  # noqa
from _common import TS_SOURCE, INSTANCES, next_thursday_after  # noqa


# --- step: timeseries ----------------------------------------------------

COLUMNS = [
    "publication_thursday", "henry_hub_this_wed", "henry_hub_prev_wed",
    "henry_hub_change_dollar",
]


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-dates", required=True,
                    help="Comma-separated YYYY-MM-DD labels")
    args = ap.parse_args()

    rows_all = {}
    for jf in sorted(TS_SOURCE.glob("*.json")):
        rows_all[jf.stem] = json.loads(jf.read_text())
    sorted_labels = sorted(rows_all)

    targets = [d.strip() for d in args.instance_dates.split(",") if d.strip()]
    INSTANCES.mkdir(parents=True, exist_ok=True)
    n = 0
    for tgt in targets:
        if tgt not in rows_all:
            print(f"[warn] {tgt}: not parsed"); continue
        history = [lbl for lbl in sorted_labels if lbl <= tgt]
        out = INSTANCES / tgt
        out.mkdir(parents=True, exist_ok=True)
        with (out / "timeseries.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for lbl in history:
                p = rows_all[lbl]
                w.writerow({
                    "publication_thursday":     lbl,
                    "henry_hub_this_wed":       p.get("henry_hub_this_wed"),
                    "henry_hub_prev_wed":       p.get("henry_hub_prev_wed"),
                    "henry_hub_change_dollar":  p.get("henry_hub_change_dollar"),
                })
        n += 1
        print(f"[ok]   {tgt}: {len(history)} rows")
    print(f"[done] wrote {n} per-instance CSVs")
    return 0


# --- step: gt ------------------------------------------------------------
def _load(label: str) -> dict | None:
    p = TS_SOURCE / f"{label}.json"
    return json.loads(p.read_text()) if p.exists() else None


def _trend(change: float | None) -> str:
    if change is None:
        return "unclear"
    if abs(change) < 0.05:
        return "flat"
    return "rising" if change > 0 else "falling"


def _find_next(label: str, max_skip: int = 4):
    cur = label
    for _ in range(max_skip):
        cur = next_thursday_after(cur)
        nxt = _load(cur)
        if nxt is not None:
            return cur, nxt
    return None, None


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-dates", required=True)
    args = ap.parse_args()
    targets = [d.strip() for d in args.instance_dates.split(",") if d.strip()]
    n = 0
    for label in targets:
        cur = _load(label)
        if cur is None:
            print(f"[skip] {label}: no parsed"); continue
        out_dir = INSTANCES / label
        if not out_dir.exists():
            print(f"[skip] {label}: no instance dir"); continue
        nxt_label, nxt = _find_next(label)
        actual_trend = _trend(nxt and nxt.get("henry_hub_change_dollar"))
        actual_future = None
        if nxt is not None:
            actual_future = {
                "next_thursday_label":         nxt_label,
                "next_henry_hub_this_wed":     nxt.get("henry_hub_this_wed"),
                "next_henry_hub_change_dollar": nxt.get("henry_hub_change_dollar"),
            }
        gt = {
            "current_week_snapshot": {
                "publication_thursday":     label,
                "henry_hub_this_wed":       cur.get("henry_hub_this_wed"),
                "henry_hub_prev_wed":       cur.get("henry_hub_prev_wed"),
                "henry_hub_change_dollar":  cur.get("henry_hub_change_dollar"),
                "direction_verb":           cur.get("verb"),
            },
            "outlook_expected_trend_actual": actual_trend,
            "actual_future_outcome":         actual_future,
            "conclusion_reference":          cur.get("highlights_verbatim") or None,
            "supply_demand_reference":       cur.get("supply_demand_text") or None,
            "storage_reference":             cur.get("storage_text") or None,
            "lng_reference":                 cur.get("lng_text") or None,
            "driver_reference_sentences":    cur.get("driver_sentences") or [],
            "risk_reference_sentences":      cur.get("risk_sentences") or [],
            "outlook_reference_sentences":   cur.get("outlook_sentences") or [],
        }
        (out_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))

        evidence = (
            f"# Evidence -- {label}\n\n"
            f"Source: `gt_source/{label}.html` (EIA Natural Gas Weekly Update)\n\n"
            f"## Current-week snapshot\n"
            f"- Henry Hub spot (this Wed): ${cur.get('henry_hub_this_wed')}/MMBtu\n"
            f"- Henry Hub spot (last Wed): ${cur.get('henry_hub_prev_wed')}/MMBtu\n"
            f"- Change: ${cur.get('henry_hub_change_dollar')} (verb: {cur.get('verb')})\n\n"
            f"## Dual-GT outlook\n"
            f"- next_thursday: `{nxt_label}`\n"
            f"- outlook_expected_trend_actual: `{actual_trend}`\n\n"
            f"## Verbatim Highlights\n{cur.get('highlights_verbatim', '')[:1800]}\n"
        )
        (out_dir / "gt_evidence.md").write_text(evidence)
        n += 1
        print(f"[ok]   {label}: outlook={actual_trend}")
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
