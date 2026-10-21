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
from _common import (
    TS_SOURCE, GT_SOURCE, INSTANCES,
    label_from_date, parse_label, iter_meetings,
)  # noqa
from _pdf_parser import parse_statement  # noqa
from _common import (
    GT_SOURCE, TS_SOURCE, INSTANCES,
    label_from_date, parse_label, iter_meetings,
)  # noqa


# --- step: timeseries ----------------------------------------------------

LANDING_PATH = Path(__file__).parent / "landing_urls.json"


COLS = [
    "meeting_label",
    "publication_date",
    "deposit_facility_rate_pct",
]


def parse_or_cache(label: str) -> dict | None:
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None
    parsed = parse_statement(pdf)
    parsed["meeting_label"] = label
    cache.write_text(json.dumps(parsed, indent=2))
    return parsed


def row_from(parsed: dict) -> dict:
    label = parsed["meeting_label"]
    d = parse_label(label)
    return {
        "meeting_label":              label,
        "publication_date":           d.isoformat(),
        "deposit_facility_rate_pct":  parsed.get("deposit_facility_rate_pct"),
    }


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    landing_data = json.loads(LANDING_PATH.read_text())
    meetings_all = landing_data["meeting_dates"]

    # Parse every PDF available so the cumulative CSV can include earlier
    # meetings for context, even when they aren't themselves instances.
    all_rows: dict[str, dict] = {}
    for iso in meetings_all:
        from datetime import date
        label = label_from_date(date.fromisoformat(iso))
        parsed = parse_or_cache(label)
        if parsed:
            all_rows[label] = row_from(parsed)
    ordered = sorted(all_rows.keys(), key=parse_label)

    for d in iter_meetings(meetings_all, args.instance_start, args.instance_end):
        label = label_from_date(d)
        if label not in all_rows:
            print(f"[skip] {label}: no raw PDF / parse failed", flush=True)
            continue
        idx = ordered.index(label)
        window = ordered[: idx + 1]
        out = INSTANCES / label
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "timeseries.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=COLS)
            wr.writeheader()
            for lab in window:
                wr.writerow(all_rows[lab])
        print(f"[ok]  {label}: cumulative {len(window)} meetings", flush=True)


# --- step: gt ------------------------------------------------------------
def _coarsen_rate_action(rate_decision: str | None) -> str:
    """Collapse fine-grained rate_decision enum to {hold, cut, hike, unclear}
    for the next-meeting outlook.expected_rate_action dual-GT."""
    if rate_decision is None:
        return "unclear"
    if rate_decision == "hold":
        return "hold"
    if rate_decision.startswith("cut"):
        return "cut"
    if rate_decision.startswith("hike"):
        return "hike"
    return "unclear"


def _load_or_parse(label: str) -> dict | None:
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    return parse_statement(pdf)


def process(label: str, next_label: str | None) -> tuple[dict | None, str | None]:
    cur = _load_or_parse(label)
    if cur is None:
        return None, None

    nxt = _load_or_parse(next_label) if next_label else None

    actual_future = None
    actual_expected_action = None
    if nxt is not None:
        actual_future = {
            "next_meeting_label":             next_label,
            "next_meeting_rate_decision":     nxt.get("rate_decision"),
            "next_meeting_deposit_facility_rate_pct": nxt.get("deposit_facility_rate_pct"),
        }
        actual_expected_action = _coarsen_rate_action(nxt.get("rate_decision"))

    gt = {
        # Deterministic snapshot for this meeting — scored by exact match.
        "current_meeting_snapshot": {
            "meeting_label":                  label,
            "rate_decision":                  cur.get("rate_decision"),
            "deposit_facility_rate_pct":      cur.get("deposit_facility_rate_pct"),
        },

        # Hard-tier deterministic dual-GT for the predictive outlook field.
        # Next-meeting actual rate action, coarsened to {hold, cut, hike, unclear}.
        "outlook_expected_rate_action_actual": actual_expected_action,
        "actual_future_outcome": actual_future,

        # Verbatim reference text for LLM-judge scoring of free-text fields.
        "conclusion_reference":               cur.get("executive_overview_text") or None,
        "inflation_assessment_reference":     cur.get("inflation_assessment_text") or None,
        "growth_assessment_reference":        cur.get("growth_assessment_text") or None,
        "risks_reference_text":               cur.get("risks_text") or None,
        "outlook_reference_text":             cur.get("outlook_text") or None,
        "key_drivers_reference_sentences":    cur.get("key_drivers_sentences") or [],
    }

    md = [
        f"# Evidence — {label}\n",
        f"Source: `gt_source/{label}.pdf` (ECB Combined monetary policy decisions and statement)\n",

        "## Current-meeting deterministic snapshot\n",
        f"- **rate_decision** -> `{cur.get('rate_decision')}`",
        f"- **deposit_facility_rate_pct** -> `{cur.get('deposit_facility_rate_pct')}`\n",

        "## Future-meeting outcome (for outlook.expected_rate_action scoring)\n",
        (f"- **outlook_expected_rate_action_actual** -> `{actual_expected_action}`\n"
         f"- **next_meeting** -> `{next_label}` "
         + ("(available)" if nxt is not None else "(NOT yet published)")
         + (f"\n- **next_meeting_rate_decision** -> `{nxt.get('rate_decision')}`" if nxt else "")),

        "\n## Verbatim opening / executive-overview block\n",
        (cur.get("executive_overview_text") or "*(not parsed)*"),

        "\n## Verbatim inflation-assessment block\n",
        (cur.get("inflation_assessment_text") or "*(not parsed)*"),

        "\n## Verbatim growth / economic-activity block\n",
        (cur.get("growth_assessment_text") or "*(not parsed)*"),

        "\n## Verbatim risk-assessment block\n",
        (cur.get("risks_text") or "*(not parsed)*"),

        "\n## Verbatim conclusion / forward-guidance block\n",
        (cur.get("outlook_text") or "*(not parsed)*"),

        "\n## Verbatim driver sentences ('due to' / 'reflecting' / 'amid' / 'on the back of')\n",
    ]
    for s in cur.get("key_drivers_sentences") or []:
        md.append(f"- {s}")

    return gt, "\n".join(md)


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    landing_data = json.loads(LANDING_PATH.read_text())
    meetings_all = landing_data["meeting_dates"]
    ordered_labels = [label_from_date(__import__("datetime").date.fromisoformat(iso))
                      for iso in meetings_all]

    for d in iter_meetings(meetings_all, args.instance_start, args.instance_end):
        label = label_from_date(d)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}: instance dir missing (no timeseries.csv)", flush=True)
            continue
        # Find the next meeting strictly after this one
        idx = ordered_labels.index(label)
        next_label = ordered_labels[idx + 1] if idx + 1 < len(ordered_labels) else None
        gt, ev = process(label, next_label)
        if gt is None:
            print(f"[skip] {label}: no PDF", flush=True)
            continue
        (out / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        (out / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: rate_decision={gt['current_meeting_snapshot']['rate_decision']}, "
              f"next_action_actual={gt['outlook_expected_rate_action_actual']}",
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
