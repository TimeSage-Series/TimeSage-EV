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
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    TS_SOURCE, INSTANCES, START_LABEL, END_LABEL, EARLIEST_RAW,
    NAMED_COUNTRIES, ENUM_FOR, country_col, TOTAL_COL, iter_months, month_label,
)
import os
import json
from _common import INSTANCES, START_LABEL, END_LABEL  # noqa: E402
ENV = Path(__file__).resolve().parent.parent / "environment"
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
    xls_path = TS_SOURCE / "PET_MOVE_IMPCUS_A2_NUS_EPC0_IM0_MBBLPD_M.xls"
    if not xls_path.exists():
        print(f"[err] missing {xls_path}; run `download.py timeseries` first",
              file=sys.stderr)
        return 1
    df = pd.read_excel(xls_path, sheet_name="Data 1", header=2)
    # df['Date'] is a datetime at month-midpoint (DD=15). Build a YYYY-MM label.
    df["as_of_data_month"] = df["Date"].dt.strftime("%Y-%m")
    df = df.set_index("as_of_data_month")
    # Build per-month dict
    by_month: dict[str, dict] = {}
    for label, row in df.iterrows():
        if label < EARLIEST_RAW:
            continue
        total = row.get(TOTAL_COL)
        if pd.isna(total):
            continue
        named_vals = {}
        listed_sum = 0.0
        for c in NAMED_COUNTRIES:
            v = row.get(country_col(c))
            if pd.isna(v):
                v = 0.0
            named_vals[ENUM_FOR[c] + "_mbbld"] = float(v)
            listed_sum += float(v)
        other = float(total) - listed_sum
        # Clamp to >= 0 (residual can occasionally be slightly negative due
        # to rounding when minor countries' rounded values sum just above
        # total; the underlying values are non-negative).
        if other < 0:
            other = 0.0
        by_month[label] = {
            "total_imports_mbbld": float(total),
            **named_vals,
            "other_mbbld": other,
        }

    header = [
        "as_of_data_month", "total_imports_mbbld",
        "canada_mbbld", "mexico_mbbld", "saudi_arabia_mbbld",
        "iraq_mbbld", "colombia_mbbld", "other_mbbld",
    ]

    sorted_months = sorted(by_month.keys())
    print(f"[ok] {len(sorted_months)} data months in range", file=sys.stderr)

    INSTANCES.mkdir(parents=True, exist_ok=True)
    n_inst = 0
    for d in iter_months(START_LABEL, END_LABEL):
        lbl = month_label(d)
        if lbl not in by_month:
            print(f"[warn] no data for {lbl}; skipping instance", file=sys.stderr)
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
                    f"{r['total_imports_mbbld']:.1f}",
                    f"{r['canada_mbbld']:.1f}",
                    f"{r['mexico_mbbld']:.1f}",
                    f"{r['saudi_arabia_mbbld']:.1f}",
                    f"{r['iraq_mbbld']:.1f}",
                    f"{r['colombia_mbbld']:.1f}",
                    f"{r['other_mbbld']:.1f}",
                ])
        n_inst += 1
    print(f"[ok] wrote {n_inst} instance CSVs", file=sys.stderr)
    return 0


# --- step: gt ------------------------------------------------------------
def load_csv(path: Path) -> list[dict]:
    with path.open() as fh:
        return list(csv.DictReader(fh))


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _dir(delta, dead=50.0):
    if delta is None:
        return None
    if delta > dead:
        return "rising"
    if delta < -dead:
        return "falling"
    return "stable"


COUNTRY_COLS = [
    ("canada_mbbld", "canada"),
    ("mexico_mbbld", "mexico"),
    ("saudi_arabia_mbbld", "saudi_arabia"),
    ("iraq_mbbld", "iraq"),
    ("colombia_mbbld", "colombia"),
    ("other_mbbld", "other"),
]

QUESTION_TEMPLATE = (ENV / "question_template.md").read_text()


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
    total = _f(last["total_imports_mbbld"])
    if prev is None:
        delta = None
    else:
        ptot = _f(prev["total_imports_mbbld"])
        delta = round(total - ptot, 1) if (total is not None and ptot is not None) else None
    direction = _dir(delta)
    # Argmax over country cols on latest row
    country_vals = {label: _f(last[col]) for col, label in COUNTRY_COLS}
    leader = max(country_vals.items(), key=lambda kv: kv[1] if kv[1] is not None else -1)[0]
    leader_value = country_vals[leader]
    leader_share = (leader_value / total * 100.0) if (total and total > 0) else 0.0

    # Short summary (factual)
    if direction is None:
        dir_phrase = "no prior month available"
        mom_phrase = ""
    else:
        mom_phrase = f"{abs(delta):.1f} mbbld {'higher' if delta > 0 else ('lower' if delta < 0 else 'flat')} vs the prior month ({direction})"
        dir_phrase = direction
    leader_pretty = leader.replace("_", " ").title()
    report = (
        f"EIA data month {period}: total U.S. crude oil imports of "
        f"{total:.1f} mbbld; "
        f"{mom_phrase}. "
        f"{leader_pretty} led the month at approximately {leader_share:.0f}% "
        f"of total imports."
    )

    gt = {
        "as_of_data_month": period,
        "total_imports_mbbld": round(total, 1),
        "mom_change_mbbld": delta,
        "mom_direction": direction,
        "leading_source_country": leader,
        "report": report,
    }
    (inst_dir / "ground_truth.json").write_text(
        json.dumps(gt, indent=2) + "\n", encoding="utf-8")

    # gt_evidence.md
    lines = [
        f"# GT evidence — {period}",
        "",
        f"Source: `gt_source/{period}.pdf` (EIA Monthly Energy Review / Petroleum "
        f"Supply Monthly companion bulletin)",
        "",
        "## Current-issue deterministic snapshot",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| total_imports_mbbld | {total:.1f} |",
        f"| mom_change_mbbld | {'null' if delta is None else f'{delta:+.1f}'} |",
        f"| mom_direction | {direction if direction else 'null'} |",
        f"| leading_source_country | {leader} |",
        f"| canada_mbbld | {country_vals['canada']:.1f} |",
        f"| mexico_mbbld | {country_vals['mexico']:.1f} |",
        f"| saudi_arabia_mbbld | {country_vals['saudi_arabia']:.1f} |",
        f"| iraq_mbbld | {country_vals['iraq']:.1f} |",
        f"| colombia_mbbld | {country_vals['colombia']:.1f} |",
        f"| other_mbbld | {country_vals['other']:.1f} |",
        "",
        "## Source",
        "",
        f"EIA dnav 'U.S. Imports by Country of Origin' XLS — latest row "
        f"`as_of_data_month={period}` of `timeseries.csv`. Total computed "
        f"from `total_imports_mbbld={total:.1f}`; MoM delta computed against "
        f"the immediately prior CSV row.",
    ]
    # Append verbatim + trigger sentences from the EIA bulletin PDF (if present).
    pdf_path = GT_SOURCE / f"{period}.pdf"
    src_text, pages = load_source_text(pdf_path)
    if src_text:
        lines.append(build_narrative_md_block(
            source_ref=f"gt_source/{period}.pdf",
            source_text=src_text,
            pages=pages,
            verbatim_label="Verbatim EIA bulletin excerpt (opening narrative)",
            max_verbatim_chars=2500,
        ))
    (inst_dir / "gt_evidence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # gt_reference.json (lightweight supporting evidence pointer)
    gt_ref = {
        "supporting_evidence": [
            {
                "observation": f"total_imports_mbbld = {total:.1f} for {period}.",
                "source": "/root/timeseries.csv (latest row)",
            },
            {
                "observation": (f"prior-month total = {_f(prev['total_imports_mbbld']):.1f}" if prev else
                                "no prior-month row available."),
                "source": ("/root/timeseries.csv (second-to-last row)" if prev else "n/a"),
            },
            {
                "observation": (f"leader column {leader}_mbbld = {leader_value:.1f}"),
                "source": "/root/timeseries.csv (latest row, argmax over country columns)",
            },
        ]
    }
    (inst_dir / "gt_reference.json").write_text(
        json.dumps(gt_ref, indent=2) + "\n", encoding="utf-8")

    # visible_reports.json (no per-period release artifact)
    (inst_dir / "visible_reports.json").write_text(json.dumps({
        "scenario_id": "eia_us_petroleum_imports_monthly_brief",
        "as_of_data_month": period,
        "accessible_artifacts": [],
    }, indent=2) + "\n", encoding="utf-8")

    # question.md (rendered)
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
