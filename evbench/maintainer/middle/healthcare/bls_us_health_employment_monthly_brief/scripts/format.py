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
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    TS_SOURCE, INSTANCES, SERIES, START_LABEL, END_LABEL, EARLIEST_RAW,
    iter_months, month_label,
)
import os
import json
from _common import INSTANCES  # noqa: E402
ENV = Path(__file__).resolve().parent.parent / "environment"
QUESTION_TEMPLATE = (ENV / "question_template.md").read_text()
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


def load_fred_csv(series_id: str) -> dict[str, float]:
    path = TS_SOURCE / f"{series_id}.csv"
    out = {}
    with path.open() as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            d = r.get("observation_date", "")
            if not d:
                continue
            ym = d[:7]
            v = r.get(series_id) or r.get(series_id.upper()) or ""
            if v in ("", "."):
                continue
            try:
                out[ym] = float(v)
            except ValueError:
                continue
    return out


def _step_timeseries() -> int:
    series = {label: load_fred_csv(sid) for label, sid in SERIES.items()}
    months = sorted(set().union(*[s.keys() for s in series.values()]))
    months = [m for m in months if m >= EARLIEST_RAW]
    print(f"[ok] {len(months)} months loaded ({months[0]} -> {months[-1]})",
          file=sys.stderr)

    by_month: dict[str, dict] = {}
    for m in months:
        if not all(m in s for s in series.values()):
            continue
        phys = series["physicians_offices"][m]
        hosp = series["hospitals"][m]
        nurs = series["nursing_care"][m]
        amb = series["ambulatory_total"][m]
        soc = series["social_assistance"][m]
        other_amb = amb - phys
        total = phys + hosp + nurs + other_amb + soc
        by_month[m] = {
            "physicians_offices": phys,
            "hospitals": hosp,
            "nursing_care": nurs,
            "other_ambulatory": other_amb,
            "social_assistance": soc,
            "total_health_employment_thousands": total,
        }

    sorted_months = sorted(by_month.keys())
    print(f"[ok] {len(sorted_months)} complete monthly rows", file=sys.stderr)

    INSTANCES.mkdir(parents=True, exist_ok=True)
    header = [
        "as_of_data_month", "physicians_offices", "hospitals",
        "nursing_care", "other_ambulatory", "social_assistance",
        "total_health_employment_thousands",
    ]
    n_inst = 0
    for d in iter_months(START_LABEL, END_LABEL):
        lbl = month_label(d)
        if lbl not in by_month:
            print(f"[warn] no data for {lbl}; skipping", file=sys.stderr)
            continue
        inst = INSTANCES / lbl
        inst.mkdir(parents=True, exist_ok=True)
        with (inst / "timeseries.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            for past in sorted_months:
                if past > lbl:
                    break
                r = by_month[past]
                w.writerow([
                    past,
                    f"{r['physicians_offices']:.1f}",
                    f"{r['hospitals']:.1f}",
                    f"{r['nursing_care']:.1f}",
                    f"{r['other_ambulatory']:.1f}",
                    f"{r['social_assistance']:.1f}",
                    f"{r['total_health_employment_thousands']:.1f}",
                ])
        n_inst += 1
    print(f"[ok] wrote {n_inst} instance CSVs", file=sys.stderr)
    return 0


# --- step: gt ------------------------------------------------------------
SUBSECTORS = ["physicians_offices", "hospitals", "nursing_care",
              "other_ambulatory", "social_assistance"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dir(delta, dead=5.0):
    if delta is None:
        return None
    if delta > dead:
        return "expanding"
    if delta < -dead:
        return "contracting"
    return "stable"


def load_csv(path: Path) -> list[dict]:
    with path.open() as fh:
        return list(csv.DictReader(fh))


def render_question(period: str) -> str:
    y, m = period.split("-")
    months_long = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    ml = f"{months_long[int(m)-1]} {y}"
    return (QUESTION_TEMPLATE
            .replace("{{period_label}}", period)
            .replace("{{month_label_long}}", ml))


def build_instance(inst_dir: Path) -> None:
    period = inst_dir.name
    rows = load_csv(inst_dir / "timeseries.csv")
    if not rows:
        return
    last = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else None
    total = _f(last["total_health_employment_thousands"])
    if prev is None:
        delta = None
        leader = None
    else:
        ptot = _f(prev["total_health_employment_thousands"])
        delta = round(total - ptot, 1) if (total is not None and ptot is not None) else None
        # Compute MoM% per subsector — argmax
        scores = {}
        for s in SUBSECTORS:
            pv = _f(prev[s])
            cv = _f(last[s])
            if pv is None or cv is None or pv == 0:
                scores[s] = float("-inf")
            else:
                scores[s] = (cv - pv) / pv
        # Argmax in declared order
        leader = max(SUBSECTORS, key=lambda s: scores[s])
    direction = _dir(delta)

    # Short summary
    if direction is None:
        summary_dir = "(no prior-month row available for MoM)"
        leader_phrase = ""
    else:
        sign = "+" if delta >= 0 else ""
        summary_dir = f"{sign}{delta:.1f}K MoM ({direction})"
        leader_pretty = leader.replace("_", " ")
        pv_leader = _f(prev[leader])
        cv_leader = _f(last[leader])
        if pv_leader and pv_leader != 0:
            pct = 100.0 * (cv_leader - pv_leader) / pv_leader
            leader_phrase = f"{leader_pretty} led sub-sector MoM growth at {pct:+.2f}%."
        else:
            leader_phrase = f"{leader_pretty} led sub-sector MoM growth."

    report = (
        f"BLS CES data month {period}: total US health-services employment "
        f"of {total:.1f}K, {summary_dir}. {leader_phrase}"
    ).strip()

    gt = {
        "as_of_data_month": period,
        "total_health_employment_thousands": round(total, 1) if total is not None else 0.0,
        "mom_change_thousands": delta,
        "mom_direction": direction,
        "leading_growth_subsector": leader,
        "report": report,
    }
    (inst_dir / "ground_truth.json").write_text(
        json.dumps(gt, indent=2) + "\n", encoding="utf-8")

    # gt_evidence.md
    lines = [
        f"# GT evidence - {period}",
        "",
        f"Source: `gt_source/{period}.pdf` (BLS Employment Situation news release PDF)",
        "",
        "## Current-issue deterministic snapshot",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| total_health_employment_thousands | {total:.1f} |",
        f"| mom_change_thousands | {'null' if delta is None else f'{delta:+.1f}'} |",
        f"| mom_direction | {direction if direction else 'null'} |",
        f"| leading_growth_subsector | {leader if leader else 'null'} |",
        f"| physicians_offices | {_f(last['physicians_offices']):.1f} |",
        f"| hospitals | {_f(last['hospitals']):.1f} |",
        f"| nursing_care | {_f(last['nursing_care']):.1f} |",
        f"| other_ambulatory | {_f(last['other_ambulatory']):.1f} |",
        f"| social_assistance | {_f(last['social_assistance']):.1f} |",
        "",
        "## Source",
        "",
        f"BLS CES sub-sector series via FRED (CES6562110001 / 6562200001 / "
        f"6562300001 / 6562100001 / 6562400001). Latest CSV row "
        f"`as_of_data_month={period}`; MoM delta computed against the "
        f"immediately prior row; leading_growth_subsector is argmax MoM "
        f"percent over the five sub-sector columns.",
    ]
    pdf_path = GT_SOURCE / f"{period}.pdf"
    src_text, pages = load_source_text(pdf_path)
    if src_text:
        lines.append(build_narrative_md_block(
            source_ref=f"gt_source/{period}.pdf",
            source_text=src_text,
            pages=pages,
            verbatim_label="Verbatim BLS Employment Situation excerpt (opening narrative)",
            max_verbatim_chars=2500,
        ))
    (inst_dir / "gt_evidence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # gt_reference.json
    se = [
        {"observation": f"total_health_employment_thousands = {total:.1f} for {period}.",
         "source": "/root/timeseries.csv (latest row, sum of five sub-sector columns)"},
        {"observation": (
            f"prior-month total = {_f(prev['total_health_employment_thousands']):.1f}" if prev else
            "no prior-month row available."),
         "source": "/root/timeseries.csv (second-to-last row)" if prev else "n/a"},
        {"observation": (
            f"leader {leader} = {_f(last[leader]):.1f}; prior = {_f(prev[leader]):.1f}" if leader else
            "no prior-month row available for leader computation."),
         "source": "/root/timeseries.csv (latest + prior row, argmax MoM% over sub-sectors)"},
    ]
    (inst_dir / "gt_reference.json").write_text(
        json.dumps({"supporting_evidence": se}, indent=2) + "\n", encoding="utf-8")

    (inst_dir / "visible_reports.json").write_text(json.dumps({
        "scenario_id": "bls_us_health_employment_monthly_brief",
        "as_of_data_month": period,
        "accessible_artifacts": [],
    }, indent=2) + "\n", encoding="utf-8")

    (inst_dir / "question.md").write_text(render_question(period), encoding="utf-8")


def _step_gt() -> int:
    insts = sorted([p for p in INSTANCES.iterdir() if p.is_dir()])
    for p in insts:
        if not (p / "timeseries.csv").exists():
            continue
        build_instance(p)
    print(f"[ok] populated {len(insts)} instances", file=sys.stderr)
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
