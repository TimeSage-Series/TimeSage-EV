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
import csv
import sys
from _common import (
    TS_SOURCE,
    INSTANCES,
    REPORT_MONTHS,
    ym_label,
    parse_nor,
)
import os
import json
from pathlib import Path
def _scenario_data_dir(script_file: str) -> Path:
    """Data directory for the scenario whose scripts/ contains `script_file`.

    Scripts live in evbench/maintainer/<tier>/<domain>/<id>/scripts/ while
    instances/ and source/ live under evbench/scenarios/.
    $TIMESAGE_DATA_ROOT overrides the data root.
    """
    spec = Path(script_file).resolve().parent.parent
    maintainer = spec.parents[2]
    rel = spec.relative_to(maintainer)
    return Path(os.environ.get("TIMESAGE_DATA_ROOT", maintainer.parent / "scenarios")) / rel

SCENARIO_DIR = _scenario_data_dir(__file__)
GT_SOURCE = SCENARIO_DIR / "gt_source"
MAINTAINER_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(MAINTAINER_ROOT / "lib"))
from narrative_extract import build_narrative_md_block, load_source_text  # noqa: E402


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> int:
    by_month: dict = {}
    for y, m in REPORT_MONTHS:
        lbl = ym_label(y, m)
        path = TS_SOURCE / f"{lbl}.html"
        if not path.exists():
            continue
        parsed = parse_nor(path.read_text(errors="ignore"))
        if "avg_daily_traffic" in parsed:
            by_month[lbl] = parsed
            print(f"parsed {lbl}: traffic={parsed.get('avg_daily_traffic')}, "
                  f"yoy={parsed.get('yoy_pct')}, "
                  f"atfm={parsed.get('atfm_delay_minutes')}", file=sys.stderr)
        else:
            print(f"PARSE_FAIL {lbl}", file=sys.stderr)

    if not by_month:
        return 1

    sorted_months = sorted(by_month.keys())

    header = ["report_month", "avg_daily_traffic", "yoy_pct",
              "peak_day_traffic", "atfm_delay_minutes"]
    INSTANCES.mkdir(parents=True, exist_ok=True)
    for y, m in REPORT_MONTHS:
        lbl = ym_label(y, m)
        if lbl not in by_month:
            continue
        inst = INSTANCES / lbl
        inst.mkdir(parents=True, exist_ok=True)
        path = inst / "timeseries.csv"
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            for past_lbl in sorted_months:
                if past_lbl > lbl:
                    break
                d = by_month[past_lbl]
                w.writerow([
                    past_lbl,
                    d.get("avg_daily_traffic", ""),
                    f"{d['yoy_pct']:+.2f}" if "yoy_pct" in d else "",
                    d.get("peak_day_traffic", ""),
                    d.get("atfm_delay_minutes", ""),
                ])
    print(f"wrote {len(by_month)} instance timeseries.csv files",
          file=sys.stderr)
    return 0


# --- step: gt ------------------------------------------------------------
def direction(pct, threshold=1.0):
    if pct is None:
        return None
    if pct > threshold:
        return "up"
    if pct < -threshold:
        return "down"
    return "flat"


def _step_gt() -> int:
    parsed_by_month: dict = {}
    for y, m in REPORT_MONTHS:
        lbl = ym_label(y, m)
        path = TS_SOURCE / f"{lbl}.html"
        if path.exists():
            parsed_by_month[lbl] = parse_nor(path.read_text(errors="ignore"))

    sorted_months = sorted(parsed_by_month.keys())
    for i, lbl in enumerate(sorted_months):
        inst = INSTANCES / lbl
        if not inst.exists():
            continue
        cur = parsed_by_month[lbl]
        prev = parsed_by_month[sorted_months[i - 1]] if i > 0 else None

        avg = cur.get("avg_daily_traffic")
        prev_avg = prev.get("avg_daily_traffic") if prev else None
        if avg is not None and prev_avg:
            mom_pct = round((avg - prev_avg) / prev_avg * 100, 2)
        else:
            mom_pct = None

        yoy_pct = cur.get("yoy_pct")

        gt = {
            "data_month": lbl,
            "avg_daily_traffic": avg,
            "mom_direction": direction(mom_pct),
            "mom_pct": mom_pct,
            "yoy_direction": direction(yoy_pct),
            "yoy_pct": yoy_pct,
            "peak_day_traffic": cur.get("peak_day_traffic"),
            "peak_day_date": cur.get("peak_day_date"),
            "atfm_delay_minutes": cur.get("atfm_delay_minutes"),
            "report": (
                f"Eurocontrol Network Operations Report for {lbl}: "
                f"average daily traffic {avg:,} flights "
                f"({yoy_pct:+.1f}% YoY"
                + (f", {mom_pct:+.1f}% MoM" if mom_pct is not None else "")
                + f"); peak day "
                f"{cur.get('peak_day_traffic','?'):,} flights on "
                f"{cur.get('peak_day_date','?')}; {cur.get('atfm_delay_minutes','?'):,} "
                f"minutes of ATFM delay."
                if avg and yoy_pct is not None
                else f"Partial extraction for {lbl} — see gt_source/{lbl}.html"
            ),
            "supporting_evidence": [
                {"observation": f"Average daily traffic of {avg:,} flights "
                                f"reported on the NOR landing page.",
                 "source": f"gt_source/{lbl}.html § Traffic-in-{lbl} headline"}
                if avg else None,
                {"observation": f"Year-over-year change of {yoy_pct:+.1f}% "
                                f"vs {cur.get('yoy_comparison_month','prior year')}.",
                 "source": f"gt_source/{lbl}.html § YoY-comparison sentence"}
                if yoy_pct is not None else None,
                {"observation": f"Peak day traffic of "
                                f"{cur.get('peak_day_traffic','?'):,} flights "
                                f"on {cur.get('peak_day_date','?')}.",
                 "source": f"gt_source/{lbl}.html § peak-day sentence"}
                if cur.get("peak_day_traffic") else None,
                {"observation": f"{cur.get('atfm_delay_minutes','?'):,} "
                                f"total minutes of ATFM delay.",
                 "source": f"gt_source/{lbl}.html § ATFM-delay sentence"}
                if cur.get("atfm_delay_minutes") else None,
            ],
        }
        gt["supporting_evidence"] = [e for e in gt["supporting_evidence"] if e]

        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2) + "\n")

        ev_md = (
            f"# GT evidence — {lbl}\n\n"
            f"Structured-descriptive summary of the Eurocontrol Network "
            f"Operations Report for {lbl}.\n\n"
            f"## Headline figures (extracted from `gt_source/{lbl}.html`)\n\n"
            f"| Field | Value |\n|---|---|\n"
            f"| Average daily traffic | {avg:,} flights |\n"
            + (f"| MoM change | {mom_pct:+.2f}% (vs {sorted_months[i-1]}) |\n"
               if mom_pct is not None else "")
            + (f"| YoY change | {yoy_pct:+.2f}% (vs {cur.get('yoy_comparison_month','prior year')}) |\n"
               if yoy_pct is not None else "")
            + (f"| Peak day | {cur.get('peak_day_traffic','?'):,} flights on "
               f"{cur.get('peak_day_date','?')} |\n"
               if cur.get("peak_day_traffic") else "")
            + (f"| ATFM delay | {cur.get('atfm_delay_minutes','?'):,} minutes |\n"
               if cur.get("atfm_delay_minutes") else "")
            + f"\n## Source\n\n"
            f"`gt_source/{lbl}.html` — Eurocontrol Network Operations "
            f"Report landing page for {lbl}, fetched from "
            f"https://www.eurocontrol.int/publication/network-operations-report-...-{lbl[:4]}\n"
        )
        # Append verbatim + trigger sentences from the NOR landing HTML.
        html_path = GT_SOURCE / f"{lbl}.html"
        # Fallback to TS_SOURCE if the HTML lives there (some scenarios mirror).
        if not html_path.exists():
            html_path = TS_SOURCE / f"{lbl}.html"
        src_text, _ = load_source_text(html_path)
        if src_text:
            ev_md += build_narrative_md_block(
                source_ref=f"gt_source/{lbl}.html",
                source_text=src_text,
                pages=None,
                verbatim_label="Verbatim NOR landing-page excerpt",
                max_verbatim_chars=2500,
            )
        (inst / "gt_evidence.md").write_text(ev_md)

        manifest = {
            "scenario_id": "eurocontrol_monthly_network_ops_brief",
            "as_of_month": lbl,
            "accessible_artifacts": [
                {"path": f"gt_source/{m}.html", "kind": "html",
                 "description": f"Eurocontrol NOR landing for {m}"}
                for m in sorted_months if m <= lbl
            ],
        }
        (inst / "visible_reports.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
        print(f"wrote GT for {lbl}: yoy={yoy_pct}, mom={mom_pct}",
              file=sys.stderr)
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
