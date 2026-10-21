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
import sys
import argparse, csv, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, GT_SOURCE, INSTANCES, iter_months, month_label, last_of_month  # noqa
from _pdf_parser import parse  # noqa
import argparse, json, sys
from _common import TS_SOURCE, INSTANCES, iter_months, month_label  # noqa


# --- step: timeseries ----------------------------------------------------

COLS = ["month_label", "period_end", "iea_demand_forecast_mbd",
        "opec_demand_forecast_mbd", "eia_demand_forecast_mbd", "consensus_range_mbd"]


def parse_or_cache(label: str):
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists(): return json.loads(cache.read_text())
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists(): return None
    p = parse(pdf); p["month_label"] = label
    cache.write_text(json.dumps(p, indent=2))
    return p


def _step_timeseries():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()
    all_rows = {}
    for pdf in sorted(GT_SOURCE.glob("*.pdf")):
        p = parse_or_cache(pdf.stem)
        if not p: continue
        y, m = map(int, pdf.stem.split("-"))
        p["period_end"] = last_of_month(y, m).isoformat()
        all_rows[pdf.stem] = p
    ordered = sorted(all_rows.keys())
    for y, m, _ in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        if label not in all_rows:
            print(f"[skip] {label}", flush=True); continue
        idx = ordered.index(label)
        out = INSTANCES / label
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "timeseries.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=COLS); wr.writeheader()
            for lab in ordered[: idx + 1]:
                r = all_rows[lab]; wr.writerow({c: r.get(c) for c in COLS})
        print(f"[ok]  {label}: cumulative {idx+1} months", flush=True)


# --- step: gt ------------------------------------------------------------
def _shift_label(curr, nxt):
    if not curr or not nxt: return None
    c = curr.get("iea_demand_forecast_mbd"); n = nxt.get("iea_demand_forecast_mbd")
    if c is None or n is None: return None
    d = n - c
    if abs(d) < 0.1: return "no_shift"
    return "demand_revision_up" if d > 0 else "demand_revision_down"


def _step_gt():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()
    cache = {p.stem: json.loads(p.read_text())
             for p in TS_SOURCE.glob("*.json") if not p.name.startswith("_")}
    ordered = sorted(cache.keys())
    for y, m, _ in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        out = INSTANCES / label
        if not out.exists() or label not in cache:
            print(f"[skip] {label}", flush=True); continue
        p = cache[label]
        idx = ordered.index(label)
        nxt = cache[ordered[idx+1]] if idx+1 < len(ordered) else None
        actual = _shift_label(p, nxt)
        vals = [v for v in (p.get("iea_demand_forecast_mbd"),
                            p.get("opec_demand_forecast_mbd"),
                            p.get("eia_demand_forecast_mbd")) if v is not None]
        central = sum(vals)/len(vals) if vals else None
        gt = {
            "conclusion_reference": (p.get("executive_summary_text") or "")[:1500],
            "consensus_demand_mbd_central_estimate": central,
            "iea_demand_forecast_mbd": p.get("iea_demand_forecast_mbd"),
            "opec_demand_forecast_mbd": p.get("opec_demand_forecast_mbd"),
            "eia_demand_forecast_mbd": p.get("eia_demand_forecast_mbd"),
            "consensus_range_mbd": p.get("consensus_range_mbd"),
            "divergence_drivers_reference": p.get("divergence_drivers_text"),
            "outlook_text_reference": p.get("outlook_text"),
            "outlook_expected_consensus_shift_actual": actual,
            "actual_future_outcome": {
                "next_month": ordered[idx+1] if idx+1 < len(ordered) else None,
                "next_iea_demand_forecast_mbd": (nxt or {}).get("iea_demand_forecast_mbd"),
            },
        }
        (out / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        ev = (f"# Evidence — {label}\n\nSource: `gt_source/{label}.pdf` "
              f"(IEF Comparative Analysis).\n\n"
              f"## Per-field citations\n\n"
              f"- **central** → `{central}`\n"
              f"- **outlook_actual** → `{actual}` (M+1 IEA demand delta)\n\n"
              f"## Verbatim Executive Summary\n\n```\n{gt['conclusion_reference']}\n```\n")
        (out / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: shift={actual} central={central}", flush=True)

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
