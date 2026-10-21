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
from _common import TS_SOURCE, GT_SOURCE, INSTANCES, iter_months, month_label, last_day_of_month  # noqa
from _pdf_parser import parse_sitrep   # noqa
from _common import GT_SOURCE, TS_SOURCE, INSTANCES, iter_months, month_label, parse_month_label  # noqa


# --- step: timeseries ----------------------------------------------------


COLS = [
    "iso_month",
    "period_end",
    "total_cases_ytd",
    "total_deaths_ytd",
    "cfr_pct",
    "mom_change_pct",
    "countries_reporting_count",
    "regions_reporting_count",
]


def parse_or_cache(label: str) -> dict | None:
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None
    parsed = parse_sitrep(pdf)
    parsed["iso_month"] = label
    cache.write_text(json.dumps(parsed, indent=2))
    return parsed


def row_from(parsed: dict) -> dict:
    y, m = parsed["iso_month"].split("-M")
    y, m = int(y), int(m)
    regions = parsed.get("regions_with_outbreak") or []
    return {
        "iso_month":  parsed["iso_month"],
        "period_end": last_day_of_month(y, m).isoformat(),
        "total_cases_ytd":           parsed.get("total_cases_ytd"),
        "total_deaths_ytd":          parsed.get("total_deaths_ytd"),
        "cfr_pct":                   parsed.get("cfr_pct"),
        "mom_change_pct":            parsed.get("mom_change_pct"),
        "countries_reporting_count": parsed.get("countries_reporting_count"),
        "regions_reporting_count":   len(regions),
    }


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    # Parse every PDF available so the cumulative CSV can include earlier months
    # for context, even when those earlier months aren't themselves instances.
    all_rows: dict[str, dict] = {}
    for pdf in sorted(GT_SOURCE.glob("*.pdf")):
        parsed = parse_or_cache(pdf.stem)
        if parsed:
            all_rows[pdf.stem] = row_from(parsed)
    ordered = sorted(all_rows.keys())

    for y, m, _last in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        if label not in all_rows:
            print(f"[skip] {label}: no raw (gap or download miss)", flush=True); continue
        idx = ordered.index(label)
        window = ordered[: idx + 1]
        out = INSTANCES / label
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "timeseries.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=COLS)
            wr.writeheader()
            for lab in window:
                wr.writerow(all_rows[lab])
        print(f"[ok]  {label}: cumulative {len(window)} months", flush=True)


# --- step: gt ------------------------------------------------------------
def _next_month_label(label: str) -> str:
    y, m = parse_month_label(label)
    if m == 12:
        return month_label(y + 1, 1)
    return month_label(y, m + 1)


def _expected_trend_from_mom(signed_pct: float | None) -> str:
    """Convert next-month signed MoM% into our outlook enum.

    Thresholds: |x| < 2 -> plateau; else direction. Null -> unclear.
    """
    if signed_pct is None:
        return "unclear"
    if abs(signed_pct) < 2.0:
        return "plateau"
    return "increasing" if signed_pct > 0 else "decreasing"


def _load_or_parse(label: str) -> dict | None:
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    return parse_sitrep(pdf)


def process(label: str) -> tuple[dict | None, str | None]:
    cur = _load_or_parse(label)
    if cur is None:
        return None, None

    # Future-month SitRep (M+1) provides the actual_future_outcome for the
    # outlook field. If M+1 is not yet published we leave it None.
    nxt_label = _next_month_label(label)
    nxt = _load_or_parse(nxt_label)

    actual_future = None
    actual_expected_trend = None
    if nxt is not None:
        actual_future = {
            "next_month_label":           nxt_label,
            "next_month_total_cases_ytd": nxt.get("total_cases_ytd"),
            "next_month_total_deaths_ytd": nxt.get("total_deaths_ytd"),
            "next_month_mom_change_pct":  nxt.get("mom_change_pct"),
            "next_month_global_risk_level": nxt.get("global_risk_level"),
        }
        actual_expected_trend = _expected_trend_from_mom(nxt.get("mom_change_pct"))

    gt = {
        # Atomic numeric snapshot for the current month (for evidence/audit)
        "current_month_snapshot": {
            "global_risk_level":         cur.get("global_risk_level"),
            "total_cases_ytd":           cur.get("total_cases_ytd"),
            "total_deaths_ytd":          cur.get("total_deaths_ytd"),
            "cfr_pct":                   cur.get("cfr_pct"),
            "mom_change_pct":            cur.get("mom_change_pct"),
            "mom_direction":             cur.get("mom_direction"),
            "countries_reporting_count": cur.get("countries_reporting_count"),
            "population_at_risk":        cur.get("population_at_risk"),
            "regions_with_outbreak":     cur.get("regions_with_outbreak"),
        },

        # Hard-tier deterministic dual-GT for the predictive outlook field.
        # 'actual_expected_trend' is what the next-month SitRep actually shows.
        "outlook_expected_trend_actual": actual_expected_trend,
        "actual_future_outcome": actual_future,

        # Verbatim reference text for LLM-judge scoring of free-text fields.
        "conclusion_reference":             cur.get("executive_overview_text") or None,
        "key_drivers_reference_sentences":  cur.get("key_drivers_sentences") or [],
        "risks_reference_sentences":        cur.get("risk_sentences") or [],
        "outlook_reference_text":           cur.get("outlook_text") or None,
        "recommendations_reference_text":   cur.get("recommendations_text") or None,
        "regional_breakdown_reference":     cur.get("regional_breakdown") or [],
    }

    md = [
        f"# Evidence — {label}\n",
        f"Source: `gt_source/{label}.pdf` (WHO Multi-country outbreak of cholera SitRep)\n",

        "## Current-month deterministic snapshot\n",
        f"- **global_risk_level** -> `{cur.get('global_risk_level')}`",
        f"- **total_cases_ytd** -> `{cur.get('total_cases_ytd')}`",
        f"- **total_deaths_ytd** -> `{cur.get('total_deaths_ytd')}`",
        f"- **cfr_pct** -> `{cur.get('cfr_pct')}`",
        f"- **mom_change_pct (signed)** -> `{cur.get('mom_change_pct')}` ({cur.get('mom_direction')})",
        f"- **countries_reporting_count** -> `{cur.get('countries_reporting_count')}`",
        f"- **population_at_risk** -> `{cur.get('population_at_risk')}`",
        f"- **regions_with_outbreak** -> `{cur.get('regions_with_outbreak')}`\n",

        "## Future-month outcome (for outlook scoring; from M+1 SitRep)\n",
        (f"- **outlook_expected_trend_actual** -> `{actual_expected_trend}`\n"
         f"- **next_month_mom_change_pct** -> `{actual_future and actual_future['next_month_mom_change_pct']}`\n"
         f"- **next_month SitRep** -> `{nxt_label}` "
         + ("(available)" if nxt is not None else "(NOT yet published)")),

        "\n## Verbatim 'Situation overview' / 'Global epidemiological update' block\n",
        (cur.get("executive_overview_text") or "*(not parsed)*"),

        "\n## Verbatim driver sentences (matches 'due to' / 'driven by' / 'intensified by')\n",
    ]
    for s in cur.get("key_drivers_sentences") or []:
        md.append(f"- {s}")
    md.append("\n## Verbatim risk sentences\n")
    for s in cur.get("risk_sentences") or []:
        md.append(f"- {s}")
    md.append("\n## Verbatim outlook block\n")
    md.append(cur.get("outlook_text") or "*(not parsed)*")
    md.append("\n## Verbatim recommendations block\n")
    md.append(cur.get("recommendations_text") or "*(not parsed)*")
    md.append("\n## Regional breakdown (from text-windows around region mentions)\n")
    for row in cur.get("regional_breakdown") or []:
        md.append(f"- **{row['region']}**: cases={row.get('cases')}")

    return gt, "\n".join(md)


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    for y, m, _last in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}: instance dir missing (no timeseries.csv)", flush=True); continue
        gt, ev = process(label)
        if gt is None:
            print(f"[skip] {label}: no PDF", flush=True); continue
        (out / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        (out / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: outlook_trend_actual={gt['outlook_expected_trend_actual']}",
              flush=True)

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
