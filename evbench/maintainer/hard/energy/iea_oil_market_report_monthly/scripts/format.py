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
from _common import GT_SOURCE, TS_SOURCE, INSTANCES, iter_months, month_label  # noqa: E402
from _pdf_parser import parse_omr  # noqa: E402


# --- step: timeseries ----------------------------------------------------

LANDING_PATH = Path(__file__).parent / "landing_urls.json"

COLS = [
    "issue_label",
    "publication_date_approx",
    "global_supply_mbd_latest",
    "brent_spot_price_usd_bbl",
]


def parse_or_cache(label: str) -> dict | None:
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None
    parsed = parse_omr(pdf)
    parsed["issue_label"] = label
    cache.write_text(json.dumps(parsed, indent=2))
    return parsed


def row_from(label: str, parsed: dict, pub_date: str | None) -> dict:
    def _num(x, ndigits=2):
        if x is None:
            return None
        try:
            return round(float(x), ndigits)
        except (TypeError, ValueError):
            return None
    return {
        "issue_label":              label,
        "publication_date_approx":  pub_date or "",
        "global_supply_mbd_latest": _num(parsed.get("global_supply_mbd_latest")),
        "brent_spot_price_usd_bbl": _num(parsed.get("brent_spot_price_usd_bbl")),
    }


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True, help="YYYY-MM inclusive")
    ap.add_argument("--instance-end",   required=True, help="YYYY-MM inclusive")
    args = ap.parse_args()

    data = json.loads(LANDING_PATH.read_text())
    issues = data["issues"]

    # Parse every PDF in the corpus (within the landing list) up front.
    all_rows: dict[str, dict] = {}
    for label in sorted(issues.keys()):
        parsed = parse_or_cache(label)
        if parsed is None:
            continue
        pub = issues.get(label, {}).get("published_approx")
        all_rows[label] = row_from(label, parsed, pub)
    ordered = sorted(all_rows.keys())

    # For each instance in the requested window, write the cumulative slice
    # ending at (and including) that instance's row.
    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        if label not in all_rows:
            print(f"[skip] {label}: no parsed row (PDF missing or parse failed)", flush=True)
            continue
        idx = ordered.index(label)
        window = ordered[: idx + 1]
        out_dir = INSTANCES / label
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "timeseries.csv").open("w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=COLS)
            wr.writeheader()
            for lab in window:
                wr.writerow(all_rows[lab])
        print(f"[ok]   {label}: cumulative {len(window)} issues "
              f"(supply={all_rows[label]['global_supply_mbd_latest']} "
              f"brent={all_rows[label]['brent_spot_price_usd_bbl']})",
              flush=True)


# --- step: gt ------------------------------------------------------------
def _load_or_parse(label: str) -> dict | None:
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    parsed = parse_omr(pdf)
    cache.write_text(json.dumps(parsed, indent=2))
    return parsed


def _next_label(label: str, all_labels: list[str]) -> str | None:
    ordered = sorted(all_labels)
    if label not in ordered:
        return None
    i = ordered.index(label)
    return ordered[i + 1] if i + 1 < len(ordered) else None


def process(label: str, all_labels: list[str], pub_dates: dict[str, str]) -> tuple[dict | None, str | None]:
    cur = _load_or_parse(label)
    if cur is None:
        return None, None

    nxt_label = _next_label(label, all_labels)
    nxt = _load_or_parse(nxt_label) if nxt_label else None

    actual_future = None
    actual_balance = None
    if nxt is not None:
        actual_balance = nxt.get("market_balance_signal_keyword")
        actual_future = {
            "next_issue_label":               nxt_label,
            "next_publication_date_approx":   pub_dates.get(nxt_label),
            "next_global_supply_mbd":         nxt.get("global_supply_mbd_latest"),
            "next_brent_spot_price_usd_bbl":  nxt.get("brent_spot_price_usd_bbl"),
            "next_market_balance_signal":     actual_balance,
        }

    gt = {
        # Deterministic current-issue snapshot.
        "current_issue_snapshot": {
            "issue_label":                   label,
            "publication_date_approx":       pub_dates.get(label),
            "global_supply_mbd_latest":      cur.get("global_supply_mbd_latest"),
            "brent_spot_price_usd_bbl":      cur.get("brent_spot_price_usd_bbl"),
            "market_balance_signal_keyword": cur.get("market_balance_signal_keyword"),
        },

        # Hard-tier deterministic dual-GT for the predictive outlook field.
        "outlook_expected_oil_market_balance_actual": actual_balance,
        "actual_future_outcome":                       actual_future,

        # Verbatim reference text for LLM-judge scoring of free-text fields.
        "highlights_reference_text":         cur.get("highlights_summary_text") or None,
        "key_drivers_reference_sentences":   cur.get("key_drivers_sentences") or [],
        "risks_reference_sentences":         cur.get("risks_sentences") or [],
        "outlook_reference_sentences":       cur.get("outlook_sentences") or [],
    }

    md = [
        f"# Evidence — IEA OMR issue {label}\n",
        f"Source: `gt_source/{label}.pdf` "
        f"(IEA Oil Market Report — Highlights, published ~{pub_dates.get(label, 'unknown')})\n",

        "## Current-issue deterministic snapshot\n",
        f"- **global_supply_mbd_latest** -> `{cur.get('global_supply_mbd_latest')}` mb/d",
        f"- **brent_spot_price_usd_bbl** -> `{cur.get('brent_spot_price_usd_bbl')}` $/bbl",
        f"- **market_balance_signal_keyword** -> `{cur.get('market_balance_signal_keyword')}` (internal — not in agent CSV)\n",

        "## Next-issue outcome (for outlook dual-GT)\n",
        (f"- **outlook_expected_oil_market_balance_actual** -> `{actual_balance}`\n"
         f"- **next_issue** -> `{nxt_label}` "
         + ("(available)" if nxt is not None else "(NOT yet published)")
         + (f"\n- **next_market_balance_signal** -> `{actual_balance}`"
            if actual_future else "")),

        "\n## Verbatim Highlights bullets (page 1)\n",
        "```",
        cur.get("highlights_summary_text") or "(not parsed)",
        "```",

        "\n## Driver-trigger sentences (matches 'driven by' / 'due to' / 'amid' / 'reflecting' / 'on the back of')\n",
    ]
    for s in cur.get("key_drivers_sentences") or []:
        md.append(f"- {s}")
    md.append("\n## Risk-trigger sentences (matches 'risk' / 'uncertainty' / 'concern' / 'headwind' / 'geopolitical')\n")
    for s in cur.get("risks_sentences") or []:
        md.append(f"- {s}")
    md.append("\n## Outlook-trigger sentences (matches 'expected' / 'forecast' / 'project' / 'in the coming months' / 'set to')\n")
    for s in cur.get("outlook_sentences") or []:
        md.append(f"- {s}")
    return gt, "\n".join(md)


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True, help="YYYY-MM inclusive")
    ap.add_argument("--instance-end",   required=True, help="YYYY-MM inclusive")
    args = ap.parse_args()

    data = json.loads(LANDING_PATH.read_text())
    pub_dates = {k: v.get("published_approx") for k, v in data["issues"].items()}

    # all_labels = every issue we have a PDF for (governs M+1 lookups).
    all_labels = sorted(p.stem for p in GT_SOURCE.glob("*.pdf"))
    if not all_labels:
        print("[err] no PDFs in gt_source/", flush=True); return

    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        inst = INSTANCES / label
        if not inst.exists():
            print(f"[skip] {label}: instance dir missing (no timeseries.csv)", flush=True); continue
        gt, ev = process(label, all_labels, pub_dates)
        if gt is None:
            print(f"[skip] {label}: PDF missing or parse failed", flush=True); continue
        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        (inst / "gt_evidence.md").write_text(ev)
        print(f"[ok]   {label}: cur_balance="
              f"{gt['current_issue_snapshot']['market_balance_signal_keyword']} "
              f"actual_future_balance={gt['outlook_expected_oil_market_balance_actual']}",
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
