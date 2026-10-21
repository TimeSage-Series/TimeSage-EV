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
from _common import TS_SOURCE, GT_SOURCE, INSTANCES, iter_meetings, parse_label  # noqa: E402
from _pdf_parser import parse_summary   # noqa: E402
import datetime as dt
from _common import GT_SOURCE, TS_SOURCE, INSTANCES, MPC_MEETINGS, iter_meetings, label_from_date, parse_label  # noqa: E402


# --- step: timeseries ----------------------------------------------------


COLS = [
    "meeting_label",
    "meeting_date",
    "current_bank_rate_pct",
    "mpc_vote",
]


def parse_or_cache(label: str) -> dict | None:
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None
    parsed = parse_summary(pdf)
    parsed["meeting_label"] = label
    cache.write_text(json.dumps(parsed, indent=2))
    return parsed


def row_from(label: str, parsed: dict) -> dict:
    # meeting_date is the ISO form of the same anchor used to build label.
    # parse_label() rebuilds the date from the label so we don't drift.
    d = parse_label(label)
    return {
        "meeting_label":         label,
        "meeting_date":          d.isoformat(),
        "current_bank_rate_pct": parsed.get("current_bank_rate_pct"),
        "mpc_vote":              parsed.get("mpc_vote"),
    }


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    # Parse every PDF available so the cumulative CSV can include earlier
    # meetings for context, even when those earlier meetings aren't
    # themselves instances.
    all_rows: dict[str, dict] = {}
    for pdf in sorted(GT_SOURCE.glob("*.pdf")):
        parsed = parse_or_cache(pdf.stem)
        if parsed:
            all_rows[pdf.stem] = row_from(pdf.stem, parsed)

    # Order by meeting_date — sort by actual date since label sorts
    # lexically by month name (e.g. April < February alphabetically).
    ordered = sorted(all_rows.keys(), key=parse_label)

    for label, _d in iter_meetings(args.instance_start, args.instance_end):
        if label not in all_rows:
            print(f"[skip] {label}: no raw (download miss)", flush=True); continue
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
def _next_meeting_label(label: str) -> str | None:
    """Return the canonical label of the meeting immediately following ``label``."""
    cur = parse_label(label)
    for s in MPC_MEETINGS:
        d = dt.date.fromisoformat(s)
        if d > cur:
            return label_from_date(d)
    return None


def _expected_rate_action_from_decision(decision: str | None) -> str:
    """Map a next-meeting decision enum to the outlook enum.

    The schema uses {hold, cut, hike, unclear}. We collapse 25bp/50bp.
    """
    if decision is None:
        return "unclear"
    if decision == "hold":
        return "hold"
    if decision.startswith("cut_"):
        return "cut"
    if decision.startswith("hike_"):
        return "hike"
    return "unclear"


def _load_or_parse(label: str) -> dict | None:
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    return parse_summary(pdf)


def process(label: str) -> tuple[dict | None, str | None]:
    cur = _load_or_parse(label)
    if cur is None:
        return None, None

    # Next-meeting (M+1) PDF provides the actual_future_outcome for the
    # outlook field. If M+1 is not yet published we leave it None.
    nxt_label = _next_meeting_label(label)
    nxt = _load_or_parse(nxt_label) if nxt_label else None

    actual_future = None
    actual_expected_rate_action = None
    if nxt is not None and nxt_label is not None:
        actual_future = {
            "next_meeting_label":         nxt_label,
            "next_meeting_decision":      nxt.get("bank_rate_decision"),
            "next_meeting_bank_rate_pct": nxt.get("current_bank_rate_pct"),
            "next_meeting_pct_change":    nxt.get("pct_change"),
            "next_meeting_mpc_vote":      nxt.get("mpc_vote"),
        }
        actual_expected_rate_action = _expected_rate_action_from_decision(
            nxt.get("bank_rate_decision")
        )

    gt = {
        # Atomic deterministic snapshot for the current meeting (drives
        # the bank_rate_decision_this_meeting exact_match scoring).
        "current_meeting_snapshot": {
            "meeting_label":         label,
            "meeting_date":          parse_label(label).isoformat(),
            "bank_rate_decision":    cur.get("bank_rate_decision"),
            "current_bank_rate_pct": cur.get("current_bank_rate_pct"),
            "mpc_vote":              cur.get("mpc_vote"),
            "pct_change":            cur.get("pct_change"),
        },

        # Hard-tier deterministic dual-GT for the predictive outlook field.
        "outlook_expected_rate_action_actual": actual_expected_rate_action,
        "actual_future_outcome": actual_future,

        # Verbatim reference text for LLM-judge scoring of free-text fields.
        "conclusion_reference":               cur.get("executive_overview_text") or None,
        "inflation_assessment_reference":     cur.get("inflation_assessment_text") or None,
        "growth_labor_assessment_reference":  cur.get("growth_labor_assessment_text") or None,
        "key_drivers_reference_sentences":    cur.get("key_drivers_sentences") or [],
        "risks_reference_text":               cur.get("risks_text") or None,
        "outlook_reference_text":             cur.get("outlook_text") or None,
    }

    md = [
        f"# Evidence — BoE MPC {label}\n",
        f"Source: `gt_source/{label}.pdf` (Bank of England Monetary Policy Summary and Minutes)\n",

        "## Current-meeting deterministic snapshot\n",
        f"- **bank_rate_decision** -> `{cur.get('bank_rate_decision')}`",
        f"- **current_bank_rate_pct** -> `{cur.get('current_bank_rate_pct')}`",
        f"- **mpc_vote** -> `{cur.get('mpc_vote')}`",
        f"- **pct_change (size of move in pp)** -> `{cur.get('pct_change')}`\n",

        "## Next-meeting outcome (for outlook scoring; from M+1 Summary)\n",
        (f"- **outlook_expected_rate_action_actual** -> `{actual_expected_rate_action}`\n"
         f"- **next_meeting_decision** -> `{actual_future and actual_future['next_meeting_decision']}`\n"
         f"- **next_meeting** -> `{nxt_label}` "
         + ("(available)" if nxt is not None else "(NOT yet published)")),

        "\n## Verbatim 'Monetary Policy Summary' opening block\n",
        (cur.get("executive_overview_text") or "*(not parsed)*"),

        "\n## Verbatim inflation-assessment block\n",
        (cur.get("inflation_assessment_text") or "*(not parsed)*"),

        "\n## Verbatim growth / labour-market assessment block\n",
        (cur.get("growth_labor_assessment_text") or "*(not parsed)*"),

        "\n## Verbatim driver sentences (matches 'due to' / 'driven by' / 'reflecting' / 'owing to')\n",
    ]
    for s in cur.get("key_drivers_sentences") or []:
        md.append(f"- {s}")
    md.append("\n## Verbatim risk language (upside / downside)\n")
    md.append(cur.get("risks_text") or "*(not parsed)*")
    md.append("\n## Verbatim forward-guidance / outlook block\n")
    md.append(cur.get("outlook_text") or "*(not parsed)*")

    return gt, "\n".join(md)


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    for label, _d in iter_meetings(args.instance_start, args.instance_end):
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}: instance dir missing (no timeseries.csv)", flush=True); continue
        gt, ev = process(label)
        if gt is None:
            print(f"[skip] {label}: no PDF", flush=True); continue
        (out / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        (out / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: outlook_action_actual={gt['outlook_expected_rate_action_actual']}",
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
