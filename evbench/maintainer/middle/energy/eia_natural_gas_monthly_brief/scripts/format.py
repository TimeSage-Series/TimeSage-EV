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
from _common import TS_SOURCE, GT_SOURCE, INSTANCES, iter_months, month_label  # noqa
from _pdf_parser import parse  # noqa
from _common import TS_SOURCE, INSTANCES, iter_months, month_label  # noqa


# --- step: timeseries ----------------------------------------------------

COLS = [
    "issue_label",
    "data_period_end",
    "total_consumption_bcfd",
    "dry_gas_production_bcfd",
    "henry_hub_spot_price_usd_mmbtu",
    "working_storage_total_bcf",
    "leading_consumption_sector",
]


def parse_or_cache(label: str) -> dict | None:
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None
    p = parse(pdf)
    p["issue_label"] = label
    cache.write_text(json.dumps(p, indent=2))
    return p


def row_from(label: str, parsed: dict) -> dict:
    return {
        "issue_label":                    label,
        "data_period_end":                parsed.get("data_period_end") or "",
        "total_consumption_bcfd":         parsed.get("total_consumption_bcfd"),
        "dry_gas_production_bcfd":        parsed.get("dry_gas_production_bcfd"),
        "henry_hub_spot_price_usd_mmbtu": parsed.get("henry_hub_spot_price_usd_mmbtu"),
        "working_storage_total_bcf":      parsed.get("working_storage_total_bcf"),
        "leading_consumption_sector":     parsed.get("leading_consumption_sector"),
    }


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    all_rows: dict[str, dict] = {}
    for pdf in sorted(GT_SOURCE.glob("*.pdf")):
        parsed = parse_or_cache(pdf.stem)
        if parsed is None:
            continue
        all_rows[pdf.stem] = row_from(pdf.stem, parsed)
    ordered = sorted(all_rows.keys())

    for y, m, _ in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        if label not in all_rows:
            print(f"[skip] {label}: no parsed row", flush=True)
            continue
        idx = ordered.index(label)
        out = INSTANCES / label
        out.mkdir(parents=True, exist_ok=True)
        with (out / "timeseries.csv").open("w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=COLS)
            wr.writeheader()
            for lab in ordered[: idx + 1]:
                wr.writerow(all_rows[lab])
        cur = all_rows[label]
        print(
            f"[ok]   {label}: cumulative {idx+1} issues "
            f"(cons={cur['total_consumption_bcfd']} "
            f"dry={cur['dry_gas_production_bcfd']} "
            f"hh={cur['henry_hub_spot_price_usd_mmbtu']} "
            f"stor={cur['working_storage_total_bcf']} "
            f"lead={cur['leading_consumption_sector']})",
            flush=True,
        )


# --- step: gt ------------------------------------------------------------
def _direction(curr: float | None, prev: float | None) -> str | None:
    if curr is None or prev is None:
        return None
    d = curr - prev
    if abs(d) < 2.0:
        return "stable"
    return "rising" if d > 0 else "falling"


def _float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    for y, m, _ in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        cache = TS_SOURCE / f"{label}.json"
        out_dir = INSTANCES / label
        if not cache.exists() or not out_dir.exists():
            print(f"[skip] {label}", flush=True)
            continue
        p = json.loads(cache.read_text())
        rows = list(csv.DictReader((out_dir / "timeseries.csv").open()))
        prev = _float(rows[-2]["total_consumption_bcfd"]) if len(rows) >= 2 else None
        curr = p.get("total_consumption_bcfd")

        gt = {
            "issue_label":                    label,
            "data_period_end":                p.get("data_period_end"),
            "total_consumption_bcfd":         curr,
            "direction_of_change_vs_prior_month": _direction(curr, prev),
            "leading_consumption_sector":     p.get("leading_consumption_sector"),
            "dry_gas_production_bcfd":        p.get("dry_gas_production_bcfd"),
            "henry_hub_spot_price_usd_mmbtu": p.get("henry_hub_spot_price_usd_mmbtu"),
            "working_storage_total_bcf":     p.get("working_storage_total_bcf"),
            "sector_breakdown_bcf":          p.get("_sector_breakdown_bcf"),
            "report_reference":       p.get("report_reference") or "",
        }
        (out_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))

        sect = gt["sector_breakdown_bcf"] or {}
        ev_lines = [
            f"# Evidence — NGM {label}",
            "",
            f"- **Source PDF:** `gt_source/{label}.pdf` (EIA Natural Gas Monthly).",
            f"- **Data period reported:** {gt['data_period_end']} "
            f"(NGM issued in {label} reports data through this month-end).",
            "",
            "## Per-field citations",
            "",
            f"- `total_consumption_bcfd` → `{curr}` — derived from Table 1 "
            f"(Summary of natural gas supply and disposition), "
            f"Consumption column for the latest available month, "
            f"divided by days in that month.",
            f"- `direction_of_change_vs_prior_month` → "
            f"`{gt['direction_of_change_vs_prior_month']}` "
            f"(current {curr} vs prior issue {prev}; ±2 Bcf/d stable band).",
            f"- `leading_consumption_sector` → "
            f"`{gt['leading_consumption_sector']}` — Table 2 "
            f"(Natural gas consumption), sector with largest "
            f"delivered-to-consumers volume.",
            f"  - Residential {sect.get('residential')} · "
            f"Commercial {sect.get('commercial')} · "
            f"Industrial {sect.get('industrial')} · "
            f"Electric power {sect.get('electric_power')} (Bcf, total month).",
            f"- `dry_gas_production_bcfd` → "
            f"`{gt['dry_gas_production_bcfd']}` — Table 1, Dry gas "
            f"production column / days in month.",
            f"- `henry_hub_spot_price_usd_mmbtu` → "
            f"`{gt['henry_hub_spot_price_usd_mmbtu']}` — Table 3 "
            f"(Selected national average natural gas prices), "
            f"Natural gas spot price column (Henry Hub, $/MMBtu per "
            f"footnote b).",
            f"- `working_storage_total_bcf` → "
            f"`{gt['working_storage_total_bcf']}` — Table 8 "
            f"(Underground natural gas storage), Working gas at end of "
            f"period.",
            "",
            "## Verbatim Highlights excerpt",
            "",
            "```",
            (p.get("report_reference") or "")[:2500],
            "```",
        ]
        (out_dir / "gt_evidence.md").write_text("\n".join(ev_lines) + "\n")
        print(
            f"[ok]   {label}: dir={gt['direction_of_change_vs_prior_month']} "
            f"lead={gt['leading_consumption_sector']}",
            flush=True,
        )

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
