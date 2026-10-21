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
from _common import INSTANCES, ENV, long_month_label  # noqa: E402
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


COLUMNS = [
    "as_of_data_month",
    "job_openings_thousands",
    "hires_thousands",
    "quits_thousands",
    "total_separations_thousands",
    "openings_to_hires_ratio",
]


def load_fred(series_id: str) -> dict[str, float]:
    path = TS_SOURCE / f"{series_id}.csv"
    out: dict[str, float] = {}
    with path.open() as fh:
        for r in csv.DictReader(fh):
            d = r.get("observation_date", "")
            if not d:
                continue
            ym = d[:7]
            v = r.get(series_id) or ""
            if v in ("", "."):
                continue
            try:
                out[ym] = float(v)
            except ValueError:
                continue
    return out


def _step_timeseries() -> int:
    series = {label: load_fred(sid) for label, sid in SERIES.items()}
    all_months = sorted(set().union(*[s.keys() for s in series.values()]))
    months = [m for m in all_months if m >= EARLIEST_RAW]
    print(f"[ok] {len(months)} months in FRED ({months[0]} -> {months[-1]})",
          file=sys.stderr)

    by_month: dict[str, dict] = {}
    for m in months:
        if not all(m in s for s in series.values()):
            continue
        jol = series["job_openings_thousands"][m]
        hil = series["hires_thousands"][m]
        qul = series["quits_thousands"][m]
        tsl = series["total_separations_thousands"][m]
        ratio = round(jol / hil, 3) if hil > 0 else None
        by_month[m] = {
            "job_openings_thousands": jol,
            "hires_thousands": hil,
            "quits_thousands": qul,
            "total_separations_thousands": tsl,
            "openings_to_hires_ratio": ratio,
        }

    sorted_months = sorted(by_month.keys())
    print(f"[ok] {len(sorted_months)} complete monthly rows", file=sys.stderr)

    INSTANCES.mkdir(parents=True, exist_ok=True)

    # Only emit instances for which a GT bulletin exists.
    gt_root = TS_SOURCE.parent / "gt_source"
    # PDFs are the canonical news-release format; tolerate legacy HTML
    # stems if a stale checkout is still using the prior pipeline.
    avail = {p.stem for p in gt_root.glob("*.pdf")} | {p.stem for p in gt_root.glob("*.html")}
    print(f"[ok] {len(avail)} GT news-release files available", file=sys.stderr)

    n_inst = 0
    for d in iter_months(START_LABEL, END_LABEL):
        lbl = month_label(d)
        if lbl not in avail:
            print(f"[skip] {lbl}: no GT bulletin", file=sys.stderr)
            continue
        if lbl not in by_month:
            print(f"[skip] {lbl}: no FRED data", file=sys.stderr)
            continue
        inst = INSTANCES / lbl
        inst.mkdir(parents=True, exist_ok=True)
        with (inst / "timeseries.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(COLUMNS)
            for past in sorted_months:
                if past > lbl:
                    break
                r = by_month[past]
                w.writerow([
                    past,
                    f"{r['job_openings_thousands']:.0f}",
                    f"{r['hires_thousands']:.0f}",
                    f"{r['quits_thousands']:.0f}",
                    f"{r['total_separations_thousands']:.0f}",
                    f"{r['openings_to_hires_ratio']}",
                ])
        n_inst += 1
    print(f"[ok] wrote {n_inst} instance CSVs", file=sys.stderr)
    return 0


# --- step: gt ------------------------------------------------------------
def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dir(delta: float | None, dead: float = 20.0) -> str | None:
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
    return (QUESTION_TEMPLATE
            .replace("{{period_label}}", period)
            .replace("{{month_label_long}}", long_month_label(period)))


def build_instance(inst_dir: Path) -> None:
    period = inst_dir.name
    rows = load_csv(inst_dir / "timeseries.csv")
    if not rows:
        return
    last = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else None
    yearly_prev = None
    if len(rows) >= 13:
        # Find the row exactly 12 months before period (label-based).
        y, m = (int(x) for x in period.split("-"))
        ym_yr = y - 1
        target_label = f"{ym_yr:04d}-{m:02d}"
        for r in rows:
            if r.get("as_of_data_month") == target_label:
                yearly_prev = r
                break

    openings = _f(last.get("job_openings_thousands"))
    if prev is not None:
        prev_op = _f(prev.get("job_openings_thousands"))
        delta = round(openings - prev_op, 1) if (openings is not None and prev_op is not None) else None
    else:
        delta = None
    direction = _dir(delta)

    if yearly_prev is not None:
        yr_op = _f(yearly_prev.get("job_openings_thousands"))
        if yr_op and openings is not None:
            yoy = round(100.0 * (openings - yr_op) / yr_op, 2)
        else:
            yoy = None
    else:
        yoy = None

    # Short summary
    if direction is None:
        delta_phrase = "(no prior-month row available for MoM)"
    else:
        sign = "+" if delta >= 0 else ""
        delta_phrase = f"{sign}{delta:.1f}K MoM ({direction})"
    if yoy is None:
        yoy_phrase = "(YoY% unavailable — insufficient history)"
    else:
        sign_y = "+" if yoy >= 0 else ""
        yoy_phrase = f"YoY {sign_y}{yoy:.2f}%"
    report = (
        f"BLS JOLTS data month {period}: Health-Care & Social Assistance "
        f"job openings of {openings:.1f}K, {delta_phrase}. {yoy_phrase}."
    ).strip()

    gt = {
        "as_of_data_month": period,
        "job_openings_thousands": round(openings, 1) if openings is not None else 0.0,
        "mom_change_thousands": delta,
        "mom_direction": direction,
        "yoy_change_pct": yoy,
        "report": report,
    }
    (inst_dir / "ground_truth.json").write_text(
        json.dumps(gt, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# GT evidence - {period}",
        "",
        f"Source: `gt_source/{period}.pdf` (BLS JOLTS news release PDF)",
        "",
        "## Current-issue deterministic snapshot",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| job_openings_thousands | {openings:.1f} |",
        f"| mom_change_thousands | {'null' if delta is None else f'{delta:+.1f}'} |",
        f"| mom_direction | {direction if direction else 'null'} |",
        f"| yoy_change_pct | {'null' if yoy is None else f'{yoy:+.2f}'} |",
        f"| hires_thousands | {_f(last.get('hires_thousands')):.1f} |",
        f"| quits_thousands | {_f(last.get('quits_thousands')):.1f} |",
        f"| total_separations_thousands | {_f(last.get('total_separations_thousands')):.1f} |",
        f"| openings_to_hires_ratio | {last.get('openings_to_hires_ratio')} |",
        "",
        "## Source",
        "",
        f"BLS JOLTS Health Care & Social Assistance (NAICS 62) sub-sector via "
        f"FRED (JTS6200JOL job openings; JTS6200HIL hires; JTS6200QUL quits; "
        f"JTS6200TSL total separations). Latest CSV row "
        f"`as_of_data_month={period}`; MoM delta computed against the "
        f"immediately prior row; YoY % computed against the row 12 positions "
        f"earlier (when available).",
    ]
    pdf_path = GT_SOURCE / f"{period}.pdf"
    src_text, pages = load_source_text(pdf_path)
    if src_text:
        lines.append(build_narrative_md_block(
            source_ref=f"gt_source/{period}.pdf",
            source_text=src_text,
            pages=pages,
            verbatim_label="Verbatim JOLTS release excerpt (opening narrative)",
            max_verbatim_chars=2500,
        ))
    (inst_dir / "gt_evidence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    se = [
        {"observation": f"job_openings_thousands = {openings:.1f} for {period}.",
         "source": "/root/timeseries.csv (latest row)"},
        {"observation": (
            f"prior-month openings = {_f(prev.get('job_openings_thousands')):.1f}" if prev else
            "no prior-month row available."),
         "source": "/root/timeseries.csv (second-to-last row)" if prev else "n/a"},
    ]
    if yearly_prev is not None:
        se.append({
            "observation": (
                f"12-months-prior openings = {_f(yearly_prev.get('job_openings_thousands')):.1f}"
            ),
            "source": "/root/timeseries.csv (row 12 positions earlier)",
        })
    (inst_dir / "gt_reference.json").write_text(
        json.dumps({"supporting_evidence": se}, indent=2) + "\n", encoding="utf-8")

    (inst_dir / "visible_reports.json").write_text(json.dumps({
        "scenario_id": "bls_jolts_healthcare_monthly_brief",
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
