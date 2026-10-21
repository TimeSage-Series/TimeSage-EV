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
from _common import TS_SOURCE, GT_SOURCE, INSTANCES, iter_iso_weeks, iso_week_label, iso_saturday  # noqa
from _pdf_parser import parse_cdtr   # noqa
from _common import GT_SOURCE, TS_SOURCE, INSTANCES, iter_iso_weeks, iso_week_label  # noqa


# --- step: timeseries ----------------------------------------------------


# Canonical threat order — kept in sync with THREAT_KEYWORDS in _pdf_parser.py.
# Each <threat>_count column is the raw keyword-density count for that threat
# in the week's CDTR PDF (a threat is "present" when count >= PRESENCE_THRESHOLD,
# but the raw count is what gives the time series real numeric variation).
THREAT_ORDER = [
    "h5n1", "h9n2", "h10n3", "h7n9",
    "mpox", "measles", "dengue", "west_nile",
    "chikungunya", "cholera", "oropouche",
    "mers_cov", "crimean_congo", "respiratory_overview",
    "polio", "salmonella", "ebola", "marburg",
    "hand_foot_mouth", "hantavirus", "mass_gathering",
    "rabies", "yellow_fever",
]

COLS = [
    "iso_week", "week_ending",
    "n_threats_present",
    "leading_topic",
    "threats_present_csv",
] + [f"{t}_count" for t in THREAT_ORDER]


def parse_or_cache(label: str) -> dict | None:
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None
    parsed = parse_cdtr(pdf)
    parsed["iso_week"] = label
    cache.write_text(json.dumps(parsed, indent=2))
    return parsed


def row_from(parsed: dict) -> dict:
    threats = set(parsed.get("threats_present") or [])
    counts = parsed.get("threat_keyword_counts") or {}
    y, w = parsed["iso_week"].split("-W"); y, w = int(y), int(w)
    row = {
        "iso_week":  parsed["iso_week"],
        "week_ending": iso_saturday(y, w).isoformat(),
        "n_threats_present": parsed.get("n_threats_present"),
        "leading_topic":     parsed.get("leading_topic"),
        "threats_present_csv": ",".join(sorted(threats)),
    }
    for t in THREAT_ORDER:
        row[f"{t}_count"] = int(counts.get(t, 0))
    return row


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    all_rows: dict[str, dict] = {}
    for pdf in sorted(GT_SOURCE.glob("*.pdf")):
        parsed = parse_or_cache(pdf.stem)
        if parsed:
            all_rows[pdf.stem] = row_from(parsed)
    ordered = sorted(all_rows.keys())

    for y, w, _sat in iter_iso_weeks(args.instance_start, args.instance_end):
        label = iso_week_label(y, w)
        if label not in all_rows:
            print(f"[skip] {label}: no raw (holiday gap or download miss)", flush=True); continue
        idx = ordered.index(label)
        window = ordered[: idx + 1]
        out = INSTANCES / label
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "timeseries.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=COLS)
            wr.writeheader()
            for lab in window:
                wr.writerow(all_rows[lab])
        print(f"[ok]  {label}: cumulative {len(window)} weeks", flush=True)


# --- step: gt ------------------------------------------------------------
def process(label: str) -> tuple[dict, str] | tuple[None, None]:
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None, None
    cache = TS_SOURCE / f"{label}.json"
    parsed = json.loads(cache.read_text()) if cache.exists() else parse_cdtr(pdf)

    gt = {
        "n_threats_present":          parsed["n_threats_present"],
        "threats_present":            parsed["threats_present"],
        "leading_topic":              parsed["leading_topic"],
        "report_reference":    parsed["executive_summary"] or None,
        # inspection-only:
        "topics_listed_in_issue":     parsed.get("topics_listed", []),
        "threat_keyword_counts":      parsed.get("threat_keyword_counts", {}),
    }

    md = [
        f"# Evidence — {label}\n",
        f"Source: `gt_source/{label}.pdf` (ECDC Communicable Disease Threats Report)\n",
        "## Per-answer-field citations\n",
        f"- **n_threats_present** -> `{gt['n_threats_present']}`",
        f"- **threats_present** -> `{gt['threats_present']}`",
        f"- **leading_topic** -> `{gt['leading_topic']}` (highest keyword density)",
        f"- **report** -> graded against verbatim Executive summary below.\n",
        "## Verbatim Executive summary (for LLM judge)\n",
        gt["report_reference"] or "*(no Executive summary section parsed)*",
        "\n## Per-threat keyword counts (presence threshold: 8)\n",
    ]
    for label_k, cnt in sorted(parsed.get("threat_keyword_counts", {}).items(), key=lambda x: -x[1]):
        if cnt > 0:
            star = " ✓" if label_k in parsed["threats_present"] else ""
            md.append(f"- {label_k}: {cnt}{star}")
    return gt, "\n".join(md)


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    for y, w, _sat in iter_iso_weeks(args.instance_start, args.instance_end):
        label = iso_week_label(y, w)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}: instance dir missing", flush=True); continue
        gt, ev = process(label)
        if gt is None:
            print(f"[skip] {label}: no PDF", flush=True); continue
        (out / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        (out / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: n_threats={gt['n_threats_present']} leading={gt['leading_topic']}",
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
