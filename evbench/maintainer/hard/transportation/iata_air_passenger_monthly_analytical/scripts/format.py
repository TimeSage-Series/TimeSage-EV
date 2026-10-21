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
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    TS_SOURCE, INSTANCES, iter_months, month_label, pdf_filename,
)
from _pdf_parser import parse_report  # noqa: E402
import json
import re
from _common import (  # noqa: E402
    GT_SOURCE, INSTANCES, iter_months, month_label, pdf_filename,
)


# --- step: timeseries ----------------------------------------------------


CSV_COLS = [
    "period",
    "total_rpk_yoy_pct",
    "load_factor_pct",
    "north_america_rpk_yoy_pct",
]


YOY_BOUND  = (-50.0, 25.0)  # plausible monthly RPK/ASK YoY %
PLF_BOUND  = (55.0, 95.0)   # plausible passenger load factor %


def _clip(v, lo: float, hi: float):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if lo <= f <= hi else None


def _flatten_row(label: str, parsed: dict) -> dict:
    h = parsed.get("headline", {}) or {}
    reg = parsed.get("regional_rpk", {}) or {}
    return {
        "period": label,
        "total_rpk_yoy_pct":    _clip(h.get("total_rpk_yoy_pct"), *YOY_BOUND),
        "load_factor_pct":      _clip(h.get("load_factor_pct"), *PLF_BOUND),
        "north_america_rpk_yoy_pct": _clip(reg.get("north_america"), *YOY_BOUND),
    }


def _write_row(w: csv.DictWriter, row: dict) -> None:
    # Render None as blank, leave numerics as-is.
    clean = {k: ("" if v is None else v) for k, v in row.items()}
    w.writerow(clean)


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--earliest-period", default="2024-01",
                    help="Earliest period to attempt parsing for cumulative TS.")
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    # Step 1: parse every available PDF in timeseries_source/ from earliest
    # to instance_end, building a master row index keyed by period.
    master: dict[str, dict] = {}
    for d in iter_months(args.earliest_period, args.instance_end):
        label = month_label(d)
        pdf = TS_SOURCE / pdf_filename(d)
        if not pdf.exists():
            print(f"[miss] {label}: PDF not found in timeseries_source/", flush=True)
            continue
        try:
            parsed = parse_report(pdf)
        except Exception as e:
            print(f"[err]  {label}: parse failed: {e}", flush=True)
            continue
        master[label] = _flatten_row(label, parsed)
        print(f"[ok]   {label}: parsed", flush=True)

    # Step 2: for each instance period, write the cumulative slice.
    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        inst = INSTANCES / label
        inst.mkdir(parents=True, exist_ok=True)
        # Window = every parsed period <= label.
        keep = sorted(p for p in master if p <= label)
        if not keep:
            print(f"[skip] {label}: no parsed rows available", flush=True)
            continue
        with (inst / "timeseries.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLS)
            w.writeheader()
            for p in keep:
                _write_row(w, master[p])
        print(f"[csv]  {label}: {len(keep)} rows", flush=True)


# --- step: gt ------------------------------------------------------------
POSITIVE_OUTLOOK_RX = re.compile(
    r"\b(robust|strong|solid|favourable|favorable|continue\s+to\s+grow|"
    r"momentum|encouraging|optimis(?:m|tic)|healthy)\b", re.I,
)
NEGATIVE_OUTLOOK_RX = re.compile(
    r"\b(weak|softening|deceleration|slowdown|concern|risk|headwind|"
    r"contraction|recession|negative)\b", re.I,
)
CAUTIOUS_OUTLOOK_RX = re.compile(
    r"\b(uncertain|cautious|mixed|monitor|watch\s+carefully|wait[- ]and[- ]see|"
    r"depends\s+on)\b", re.I,
)

REGION_KEYS = ["asia_pacific", "europe", "north_america",
               "latin_america", "africa", "middle_east"]


def classify_outlook(text: str) -> str:
    """positive | cautious | negative."""
    if not text:
        return "cautious"
    pos = len(POSITIVE_OUTLOOK_RX.findall(text))
    neg = len(NEGATIVE_OUTLOOK_RX.findall(text))
    cau = len(CAUTIOUS_OUTLOOK_RX.findall(text))
    if pos > neg + cau:
        return "positive"
    if neg > pos:
        return "negative"
    return "cautious"


def rank_regions(regional_rpk: dict) -> tuple[list[str], list[str]]:
    """Return (outperforming, underperforming) lists by RPK YoY %.

    Top-2 and bottom-2 by numeric value; regions with None are excluded.
    Falls back to ([], []) if too few regions have data.
    """
    items = [(k, v) for k, v in regional_rpk.items() if v is not None]
    if len(items) < 3:
        return [], []
    items.sort(key=lambda kv: kv[1], reverse=True)
    top = [k for k, _ in items[:2]]
    bot = [k for k, _ in items[-2:]]
    return top, bot


def growth_direction(rpk_total: float | None) -> str:
    if rpk_total is None:
        return "flat"
    if rpk_total > 0.5:
        return "growth"
    if rpk_total < -0.5:
        return "contraction"
    return "flat"


def process(label: str) -> tuple[dict, str] | None:
    pdf = GT_SOURCE / f"iata_passenger_{label}.pdf"
    if not pdf.exists():
        return None
    try:
        parsed = parse_report(pdf)
    except Exception as e:
        print(f"[err] {label}: parse failed: {e}", flush=True)
        return None

    head = parsed["headline"]
    reg = parsed["regional_rpk"]
    outlook_text = parsed["outlook_text"]
    drivers = parsed["driver_labels"][:5] or ["other"]
    over, under = rank_regions(reg)

    rpk_total = head.get("total_rpk_yoy_pct")
    gt = {
        "rpk_growth_direction": growth_direction(rpk_total),
        "rpk_growth_magnitude_pct": (round(rpk_total, 2)
                                     if rpk_total is not None else 0.0),
        "key_drivers": drivers,
        "outperforming_regions": over,
        "underperforming_regions": under,
        "outlook_tone": classify_outlook(outlook_text),
        "supporting_evidence": [
            {"section_or_page": "page 1 — headline KPI block",
             "quote": (parsed["evidence_sentences"][0]
                       if parsed["evidence_sentences"] else "")},
            {"section_or_page": "regional commentary",
             "quote": (parsed["evidence_sentences"][1]
                       if len(parsed["evidence_sentences"]) > 1 else "")},
            {"section_or_page": "Outlook / What to watch",
             "quote": outlook_text[:300].strip()},
        ],
    }
    # Drop empty quotes — LLM judge will demand non-empty.
    gt["supporting_evidence"] = [e for e in gt["supporting_evidence"] if e["quote"]]

    md_lines = [
        f"# Evidence — IATA Air Passenger Market Analysis {label}\n",
        "## Per-answer-field citations\n",
        f"- **rpk_growth_direction** -> `{gt['rpk_growth_direction']}`",
        f"  - Headline RPK YoY = {rpk_total}% (page 1).",
        f"- **rpk_growth_magnitude_pct** -> `{gt['rpk_growth_magnitude_pct']}`",
        f"- **key_drivers** (keyword classifier guess) -> `{drivers}`",
        "  - LLM judge re-reads the report body to confirm against the controlled vocab.",
        f"- **outperforming_regions** -> `{over}`  |  **underperforming_regions** -> `{under}`",
        "  - Ranking is from the regional RPK YoY % cells; ties broken by table order.",
        f"- **outlook_tone** -> `{gt['outlook_tone']}`  (heuristic over Outlook block)",
        "",
        "## Evidence sentence pool\n",
        *(f"- {s}" for s in parsed["evidence_sentences"]),
        "",
        "## Outlook block (verbatim, truncated 800 chars)\n",
        outlook_text[:800],
    ]
    return gt, "\n".join(md_lines)


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        out = process(label)
        if out is None:
            print(f"[skip] {label}: missing PDF", flush=True); continue
        gt, ev = out
        inst = INSTANCES / label
        inst.mkdir(parents=True, exist_ok=True)
        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        (inst / "gt_evidence.md").write_text(ev)
        print(f"[ok]   {label}: dir={gt['rpk_growth_direction']} "
              f"tone={gt['outlook_tone']} drivers={gt['key_drivers']}",
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
