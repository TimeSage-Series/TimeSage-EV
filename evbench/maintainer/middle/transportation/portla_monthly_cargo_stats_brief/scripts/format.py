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
import csv, sys
from _common import (
    TS_SOURCE, INSTANCES, YEARS, REPORT_MONTHS, parse_historical_page,
)
import os
import csv, json, sys
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
    for y in YEARS:
        path = TS_SOURCE / f"{y}.html"
        if not path.exists():
            continue
        by_month.update(parse_historical_page(path.read_text(errors="ignore"), y))
    sorted_months = sorted(by_month.keys())
    print(f"parsed {len(sorted_months)} months", file=sys.stderr)

    header = ["report_month", "total_teus", "loaded_imports", "empty_imports",
              "total_imports", "loaded_exports", "empty_exports",
              "total_exports", "yoy_pct"]
    INSTANCES.mkdir(parents=True, exist_ok=True)
    # Use integer truncation (int(x)) to match the shipped ground_truth.json
    # convention. Earlier versions of this script used Python's :.0f format
    # which rounds .5+ upward; that produced off-by-one CSVs (e.g. 905026
    # vs GT 905025 for 2024-10) and broke R-gate deterministic re-derivation.
    for y, m in REPORT_MONTHS:
        lbl = f"{y}-{m:02d}"
        if lbl not in by_month:
            continue
        inst = INSTANCES / lbl
        inst.mkdir(parents=True, exist_ok=True)
        with (inst / "timeseries.csv").open("w", newline="") as f:
            w = csv.writer(f); w.writerow(header)
            for past in sorted_months:
                if past > lbl:
                    break
                d = by_month[past]
                w.writerow([
                    past,
                    str(int(d['total_teus'])),
                    str(int(d['loaded_imports'])),
                    str(int(d['empty_imports'])),
                    str(int(d['total_imports'])),
                    str(int(d['loaded_exports'])),
                    str(int(d['empty_exports'])),
                    str(int(d['total_exports'])),
                    f"{d['yoy_pct']:+.2f}",
                ])
    return 0


# --- step: gt ------------------------------------------------------------
def direction(pct, thresh=1.0):
    if pct is None:
        return None
    if pct > thresh: return "up"
    if pct < -thresh: return "down"
    return "flat"


def balance(imports, exports):
    if imports + exports == 0:
        return None
    ratio = (imports - exports) / (imports + exports)
    if ratio > 0.05: return "import_dominant"
    if ratio < -0.05: return "export_dominant"
    return "near_balanced"


def _step_gt() -> int:
    by_month: dict = {}
    for y in YEARS:
        path = TS_SOURCE / f"{y}.html"
        if path.exists():
            by_month.update(parse_historical_page(path.read_text(errors="ignore"), y))
    sorted_months = sorted(by_month.keys())
    n = 0
    for i, lbl in enumerate(sorted_months):
        if lbl not in {f"{y}-{m:02d}" for y, m in REPORT_MONTHS}:
            continue
        cur = by_month[lbl]
        prev = by_month.get(sorted_months[i-1]) if i > 0 else None
        mom_pct = ((cur["total_teus"] - prev["total_teus"]) / prev["total_teus"] * 100
                   if prev and prev["total_teus"] else None)
        yoy_pct = cur["yoy_pct"]
        gt = {
            "report_month": lbl,
            "total_teus": int(cur["total_teus"]),
            "mom_direction": direction(mom_pct, thresh=2.0),
            "mom_pct": round(mom_pct, 2) if mom_pct is not None else None,
            "yoy_direction": direction(yoy_pct, thresh=2.0),
            "yoy_pct": yoy_pct,
            "import_export_balance": balance(
                cur["loaded_imports"], cur["loaded_exports"]),
            "loaded_imports": int(cur["loaded_imports"]),
            "loaded_exports": int(cur["loaded_exports"]),
            "report": (
                f"Port of Los Angeles {lbl}: total volume "
                f"{int(cur['total_teus']):,} TEUs ({yoy_pct:+.1f}% YoY"
                + (f", {mom_pct:+.1f}% MoM" if mom_pct is not None else "")
                + f"). Loaded imports {int(cur['loaded_imports']):,} TEUs vs "
                f"loaded exports {int(cur['loaded_exports']):,} TEUs."
            ),
            "supporting_evidence": [
                {"observation": f"Total TEUs of {int(cur['total_teus']):,} "
                                f"for {lbl}.",
                 "source": f"gt_source/{lbl[:4]}.html § monthly cargo table"},
                {"observation": f"YoY change of {yoy_pct:+.2f}% from prior-year "
                                f"same month.",
                 "source": f"gt_source/{lbl[:4]}.html § Prior Year Change column"},
                {"observation": f"Loaded imports {int(cur['loaded_imports']):,} "
                                f"vs loaded exports {int(cur['loaded_exports']):,}.",
                 "source": f"gt_source/{lbl[:4]}.html § monthly cargo table"},
            ],
        }
        if mom_pct is not None:
            gt["supporting_evidence"].append({
                "observation": f"Month-over-month change of {mom_pct:+.2f}% "
                               f"vs {sorted_months[i-1]}.",
                "source": "Computed from instances/<prior_month>/timeseries.csv "
                          "cumulative entry",
            })
        inst = INSTANCES / lbl
        inst.mkdir(parents=True, exist_ok=True)
        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2) + "\n")
        ev = (
            f"# GT evidence — {lbl}\n\n"
            f"## Headline figures\n\n"
            f"| Field | Value |\n|---|---|\n"
            f"| Total TEUs | {int(cur['total_teus']):,} |\n"
            f"| Loaded imports | {int(cur['loaded_imports']):,} |\n"
            f"| Loaded exports | {int(cur['loaded_exports']):,} |\n"
            f"| YoY% (Prior Year Change column) | {yoy_pct:+.2f}% |\n"
            + (f"| MoM% (computed) | {mom_pct:+.2f}% |\n" if mom_pct is not None else "")
            + f"\n## Source\n\n"
            f"`gt_source/{lbl[:4]}.html` — Port of Los Angeles Container "
            f"Statistics historical-TEU page for {lbl[:4]}. Row for {lbl[5:7]}-th month.\n"
        )
        # Append verbatim + trigger sentences from the per-month HTML release
        # (if downloaded). Falls back to the year-summary HTML when missing.
        html_path = GT_SOURCE / f"{lbl}.html"
        if not html_path.exists():
            html_path = GT_SOURCE / f"{lbl[:4]}.html"
        src_text, _ = load_source_text(html_path)
        if src_text:
            ev += build_narrative_md_block(
                source_ref=f"gt_source/{html_path.name}",
                source_text=src_text,
                pages=None,
                verbatim_label="Verbatim Port-of-LA release excerpt",
                max_verbatim_chars=2500,
            )
        (inst / "gt_evidence.md").write_text(ev)
        manifest = {
            "scenario_id": "portla_monthly_cargo_stats_brief",
            "as_of_report_month": lbl,
            "accessible_artifacts": [
                {"path": f"gt_source/{y}.html", "kind": "html",
                 "description": f"Port-of-LA historical-TEU page for {y}"}
                for y in YEARS if (TS_SOURCE / f"{y}.html").exists()
                and int(lbl[:4]) >= y
            ],
        }
        (inst / "visible_reports.json").write_text(json.dumps(manifest, indent=2) + "\n")
        n += 1
    print(f"wrote GT for {n} months", file=sys.stderr)
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
