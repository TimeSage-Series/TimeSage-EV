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
from _common import TS_SOURCE, INSTANCES, iter_months, month_label  # noqa
from _common import (  # noqa
    INSTANCES, TS_SOURCE, iter_months, month_label, month_label_long, html_url_for,
)


# --- step: timeseries ----------------------------------------------------

COLUMNS = [
    "data_month",
    "general_activity_index_current", "production_index_current",
    "new_orders_index_current", "shipments_index_current",
    "employment_index_current", "company_outlook_index_current",
    "outlook_uncertainty_index_current",
    "direction",
]


def _row(label, parsed):
    return {**{c: parsed.get(c) for c in COLUMNS if c != "data_month"},
            "data_month": label}


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    args = ap.parse_args()
    parsed_all = {jf.stem: json.loads(jf.read_text())
                  for jf in sorted(TS_SOURCE.glob("*.json"))}
    sorted_labels = sorted(parsed_all)
    INSTANCES.mkdir(parents=True, exist_ok=True)
    n = 0
    for y, m in iter_months(args.start, args.end):
        label = month_label(y, m)
        if label not in parsed_all:
            print(f"[warn] {label}: not parsed"); continue
        history = [lbl for lbl in sorted_labels if lbl <= label]
        out_dir = INSTANCES / label
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "timeseries.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for lbl in history:
                w.writerow(_row(lbl, parsed_all[lbl]))
        n += 1
        print(f"[ok]   {label}: {len(history)} rows")
    print(f"[done] wrote {n} per-instance CSVs")
    return 0


# --- step: gt ------------------------------------------------------------
def _last_row(path: Path) -> dict:
    with path.open() as fh:
        return list(csv.DictReader(fh))[-1]


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    args = ap.parse_args()
    n = 0
    for y, m in iter_months(args.start, args.end):
        label = month_label(y, m)
        out_dir = INSTANCES / label
        csv_path = out_dir / "timeseries.csv"
        if not csv_path.exists():
            print(f"[skip] {label}: no csv"); continue
        row = _last_row(csv_path)
        parsed = json.loads((TS_SOURCE / f"{label}.json").read_text())
        snap = {k: row[k] for k in [
            "general_activity_index_current", "production_index_current",
            "new_orders_index_current", "shipments_index_current",
            "employment_index_current", "company_outlook_index_current",
            "outlook_uncertainty_index_current", "direction",
        ]}
        for k in list(snap.keys()):
            if snap[k] in ("", "None", None):
                snap[k] = None
            else:
                try: snap[k] = float(snap[k])
                except (ValueError, TypeError): pass

        short = parsed.get("narrative_verbatim") or parsed.get("summary_verbatim")
        gt = {
            "as_of_data_month":   label,
            "current_snapshot":   snap,
            "report_reference": short,
            "source_url":         html_url_for(y, m),
        }
        (out_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        evidence = (
            f"# Evidence -- Dallas Fed Texas Manufacturing Outlook Survey ({label})\n\n"
            f"## Source\n"
            f"- Month: **{month_label_long(y, m)}** ({label})\n"
            f"- URL: {html_url_for(y, m)}\n"
            f"- Local snapshot: `gt_source/{label}.html`\n\n"
            f"## Current-month diffusion indexes\n"
            f"- **General Business Activity**: {snap['general_activity_index_current']}\n"
            f"- Production: {snap['production_index_current']}\n"
            f"- New Orders: {snap['new_orders_index_current']}\n"
            f"- Shipments: {snap['shipments_index_current']}\n"
            f"- Employment: {snap['employment_index_current']}\n"
            f"- Company Outlook: {snap['company_outlook_index_current']}\n"
            f"- Outlook Uncertainty: {snap['outlook_uncertainty_index_current']}\n"
            f"- Direction (sign of general activity): **{snap['direction']}**\n\n"
            f"## Verbatim narrative\n{short or '*(not parsed)*'}\n"
        )
        (out_dir / "gt_evidence.md").write_text(evidence)
        n += 1
        print(f"[ok]   {label}: ga={snap['general_activity_index_current']} dir={snap['direction']}")
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
