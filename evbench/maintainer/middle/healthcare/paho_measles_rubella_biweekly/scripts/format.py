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
from _common import (TS_SOURCE, GT_SOURCE, INSTANCES,
                     iter_biweekly_issues, biweekly_label,
                     parse_biweekly_label, paho_saturday)  # noqa
from _pdf_parser import parse_paho_bulletin   # noqa
from _common import (GT_SOURCE, TS_SOURCE, INSTANCES,
                     iter_biweekly_issues, biweekly_label,
                     parse_biweekly_label, paho_saturday)  # noqa
MAINTAINER_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(MAINTAINER_ROOT / "lib"))
from narrative_extract import build_narrative_md_block, load_source_text  # noqa: E402


# --- step: timeseries ----------------------------------------------------


COLS = [
    "issue_label", "week_ending",
    "n_countries_with_cases",
    "confirmed_measles_cases_total",
    "leading_country_by_cases",
]


def parse_or_cache(label: str) -> dict | None:
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None
    parsed = parse_paho_bulletin(pdf)
    parsed["issue_label"] = label
    cache.write_text(json.dumps(parsed, indent=2))
    return parsed


def row_from(parsed: dict) -> dict:
    y, _w1, w2 = parse_biweekly_label(parsed["issue_label"])
    return {
        "issue_label": parsed["issue_label"],
        "week_ending": paho_saturday(y, w2).isoformat(),
        "n_countries_with_cases":        parsed.get("n_countries_with_cases"),
        "confirmed_measles_cases_total": parsed.get("confirmed_measles_cases_total"),
        "leading_country_by_cases":      parsed.get("leading_country_by_cases"),
    }


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
    # Order by Saturday of the LATTER week (paho_saturday on w2).
    ordered = sorted(
        all_rows.keys(),
        key=lambda lab: (
            (lambda yw: paho_saturday(yw[0], yw[2]))(parse_biweekly_label(lab))
        ),
    )

    for y, w1, w2, _sat in iter_biweekly_issues(args.instance_start, args.instance_end):
        label = biweekly_label(y, w1, w2)
        if label not in all_rows:
            print(f"[skip] {label}: no raw (missing PDF or parse failure)", flush=True); continue
        idx = ordered.index(label)
        window = ordered[: idx + 1]
        out = INSTANCES / label
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "timeseries.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=COLS)
            wr.writeheader()
            for lab in window:
                wr.writerow(all_rows[lab])
        print(f"[ok]  {label}: cumulative {len(window)} issues", flush=True)


# --- step: gt ------------------------------------------------------------
def load_parsed(label: str) -> dict | None:
    cache = TS_SOURCE / f"{label}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    pdf = GT_SOURCE / f"{label}.pdf"
    if not pdf.exists():
        return None
    parsed = parse_paho_bulletin(pdf)
    parsed["issue_label"] = label
    cache.write_text(json.dumps(parsed, indent=2))
    return parsed


def _ordered_issue_labels() -> list[str]:
    labels: list[str] = []
    for pdf in GT_SOURCE.glob("*.pdf"):
        labels.append(pdf.stem)
    labels.sort(
        key=lambda lab: (
            (lambda yw: paho_saturday(yw[0], yw[2]))(parse_biweekly_label(lab))
        ),
    )
    return labels


def _direction(now_total: int | None, two_ago_total: int | None) -> str:
    if now_total is None or two_ago_total is None or two_ago_total <= 0:
        return "stable"
    rel = (now_total - two_ago_total) / two_ago_total
    if rel > 0.05:
        return "increasing"
    if rel < -0.05:
        return "decreasing"
    return "stable"


def process(label: str, ordered: list[str]) -> tuple[dict, str] | tuple[None, None]:
    parsed = load_parsed(label)
    if parsed is None:
        return None, None

    # Direction of change vs 2 periods ago (i.e. the issue two cycles back).
    direction = "stable"
    two_ago_label: str | None = None
    if label in ordered:
        idx = ordered.index(label)
        if idx - 2 >= 0:
            two_ago_label = ordered[idx - 2]
            two_ago_parsed = load_parsed(two_ago_label)
            direction = _direction(
                parsed.get("confirmed_measles_cases_total"),
                two_ago_parsed.get("confirmed_measles_cases_total") if two_ago_parsed else None,
            )

    gt = {
        "total_confirmed_measles_cases_this_period": parsed.get("confirmed_measles_cases_total"),
        "leading_country_by_cases":                  parsed.get("leading_country_by_cases"),
        "n_countries_reporting_cases":               parsed.get("n_countries_with_cases"),
        "direction_of_change_vs_2_periods_ago":      direction,
        "report_reference":                   parsed.get("descriptive_caption") or None,
        # inspection-only:
        "descriptive_caption_reference":             parsed.get("descriptive_caption") or "",
        "country_measles_counts":                    parsed.get("country_measles_counts", {}),
        "comparison_two_periods_ago_label":          two_ago_label,
        "total_from_row":                            parsed.get("confirmed_measles_cases_total_from_row"),
        "total_from_sum":                            parsed.get("confirmed_measles_cases_total_from_sum"),
    }

    md = [
        f"# Evidence — {label}\n",
        f"Source: `gt_source/{label}.pdf` (PAHO Measles-Rubella bi-Weekly Bulletin)\n",
        "## Per-answer-field citations\n",
        f"- **total_confirmed_measles_cases_this_period** -> `{gt['total_confirmed_measles_cases_this_period']}`",
        f"   (TOTAL-row value: `{gt['total_from_row']}`; per-country sum: `{gt['total_from_sum']}`)",
        f"- **leading_country_by_cases** -> `{gt['leading_country_by_cases']}`",
        f"- **n_countries_reporting_cases** -> `{gt['n_countries_reporting_cases']}`",
        f"- **direction_of_change_vs_2_periods_ago** -> `{gt['direction_of_change_vs_2_periods_ago']}`"
        f" (compared to `{gt['comparison_two_periods_ago_label'] or 'n/a'}`)",
        f"- **report** -> graded against descriptive caption below.\n",
        "## Verbatim descriptive caption (for LLM judge)\n",
        gt["descriptive_caption_reference"] or "*(no descriptive caption parsed)*",
        "\n## Extracted per-country confirmed-measles counts\n",
    ]
    for country, n in sorted(
        gt["country_measles_counts"].items(), key=lambda kv: (-kv[1], kv[0])
    ):
        if n > 0:
            md.append(f"- {country}: {n}")
    if not any(n > 0 for n in gt["country_measles_counts"].values()):
        md.append("*(no positive per-country counts extracted)*")
    return gt, "\n".join(md)


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    ordered = _ordered_issue_labels()
    for y, w1, w2, _sat in iter_biweekly_issues(args.instance_start, args.instance_end):
        label = biweekly_label(y, w1, w2)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}: instance dir missing", flush=True); continue
        gt, ev = process(label, ordered)
        if gt is None:
            print(f"[skip] {label}: no PDF", flush=True); continue
        (out / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        src_text, src_pages = load_source_text(GT_SOURCE / f"{label}.pdf")
        if src_text:
            ev = ev.rstrip() + "\n\n" + build_narrative_md_block(
                f"gt_source/{label}.pdf", src_text, pages=src_pages,
            )
        (out / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: total={gt['total_confirmed_measles_cases_this_period']} "
              f"n_countries={gt['n_countries_reporting_cases']} "
              f"leading={gt['leading_country_by_cases']} dir={gt['direction_of_change_vs_2_periods_ago']}",
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
