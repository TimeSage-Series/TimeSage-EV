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
import os
import csv
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import ENV, INSTANCES, month_label_long  # noqa: E402
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

ROOT = _scenario_data_dir(__file__)
INSTANCES_DIR = ROOT / "instances"
MAINTAINER_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(MAINTAINER_ROOT / "lib"))
from narrative_extract import build_narrative_md_block, load_source_text  # noqa: E402


# --- step: timeseries ----------------------------------------------------




ROOT = _scenario_data_dir(__file__)
FIXTURE = ROOT / "timeseries_source" / "wasde_extracted.json"
INSTANCES_DIR = ROOT / "instances"

# Instance window (mirrors scenario.yaml). Only periods within this window
# get their own instance dir; earlier periods (2022-01..2024-04) live only
# as historical rows in those instance CSVs.
INSTANCE_WINDOW_START = "2024-04"
INSTANCE_WINDOW_END = "2026-05"

COLUMNS = [
    "release_label", "release_year", "release_month", "marketing_year",
    "corn_us_ending_stocks_mbu", "corn_us_ending_stocks_mom_pct",
    "soybeans_us_ending_stocks_mbu", "soybeans_us_ending_stocks_mom_pct",
    "wheat_us_ending_stocks_mbu", "wheat_us_ending_stocks_mom_pct",
    "corn_world_ending_stocks_mmt",
    "soybeans_world_ending_stocks_mmt",
    "wheat_world_ending_stocks_mmt",
]


def compute_mom_pct(rows: list[dict], idx: int, col: str) -> float | None:
    if idx == 0:
        return None
    prev = rows[idx - 1].get(col)
    cur = rows[idx].get(col)
    if prev in (None, 0) or cur is None:
        return None
    return round(100.0 * (cur - prev) / prev, 2)


def _step_timeseries() -> int:
    if not FIXTURE.exists():
        print(f"missing fixture: {FIXTURE}. Run the extractor first.")
        return 1
    raw = json.loads(FIXTURE.read_text())
    periods = sorted(raw.keys())
    rows: list[dict] = []
    for p in periods:
        d = dict(raw[p])
        d["release_label"] = p
        rows.append(d)
    # Compute MoM % columns for US ending stocks.
    for i, _ in enumerate(rows):
        for crop in ("corn", "soybeans", "wheat"):
            col = f"{crop}_us_ending_stocks_mbu"
            rows[i][f"{crop}_us_ending_stocks_mom_pct"] = compute_mom_pct(rows, i, col)

    INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
    n_written = 0
    for end_idx, end_row in enumerate(rows):
        period = end_row["release_label"]
        # Only emit instances within the configured window.
        if not (INSTANCE_WINDOW_START <= period <= INSTANCE_WINDOW_END):
            continue
        inst_dir = INSTANCES_DIR / period
        inst_dir.mkdir(parents=True, exist_ok=True)
        csv_path = inst_dir / "timeseries.csv"
        with csv_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for r in rows[: end_idx + 1]:
                w.writerow({c: r.get(c, "") for c in COLUMNS})
        n_written += 1
    print(f"wrote {n_written} instance CSVs (periods {INSTANCE_WINDOW_START}..{INSTANCE_WINDOW_END})")
    return 0


# --- step: gt ------------------------------------------------------------
GT_SOURCE = ROOT / "gt_source"

US_COLS = {
    "corn":     ("corn_us_ending_stocks_mbu",     "corn_us_ending_stocks_mom_pct"),
    "soybeans": ("soybeans_us_ending_stocks_mbu", "soybeans_us_ending_stocks_mom_pct"),
    "wheat":    ("wheat_us_ending_stocks_mbu",    "wheat_us_ending_stocks_mom_pct"),
}
WORLD_COLS = {
    "corn":     "corn_world_ending_stocks_mmt",
    "soybeans": "soybeans_world_ending_stocks_mmt",
    "wheat":    "wheat_world_ending_stocks_mmt",
}


def canonical_season(month: int) -> str | None:
    if month in (5, 6, 7, 8, 9):
        return "corn"
    if month in (8, 9, 10, 11):
        return "soybeans"
    if month in (5, 6, 7):
        return "wheat"
    return None


def derive_gt(rows: list[dict]) -> dict:
    latest = rows[-1]
    prior = rows[-2] if len(rows) >= 2 else None
    moms = {
        c: abs(float(latest[mom_col]))
        for c, (_, mom_col) in US_COLS.items()
        if latest.get(mom_col) not in ("", None)
    }
    if not moms:
        dominant = "mixed"
    else:
        max_val = max(moms.values())
        leaders = [c for c, v in moms.items() if abs(v - max_val) < 0.5]
        if len(leaders) > 1:
            cs = canonical_season(int(latest["release_month"]))
            dominant = cs if cs in leaders else "mixed"
        else:
            dominant = leaders[0]

    if dominant == "mixed":
        # No defensible per-commodity values to report; degrade gracefully.
        return {
            "dominant_us_commodity": "mixed",
            "dominant_us_latest_mbu": 0,
            "dominant_us_mom_pct": 0.0,
            "dominant_world_direction": "stable",
            "report": "Two commodities tied within 0.5 pp on MoM ending-stocks; no single dominant story this release.",
            "as_of_release_month": latest["release_label"],
        }

    lvl_col, mom_col = US_COLS[dominant]
    world_col = WORLD_COLS[dominant]
    latest_lvl = float(latest[lvl_col])
    latest_mom = float(latest[mom_col])
    world_dir = "stable"
    if prior and prior.get(world_col) and latest.get(world_col):
        prev_w = float(prior[world_col])
        cur_w = float(latest[world_col])
        if prev_w > 0:
            delta_pct = 100.0 * (cur_w - prev_w) / prev_w
            # NOTE: world stocks growing = loosening; shrinking = tightening.
            if delta_pct > 0.5:
                world_dir = "loosening"
            elif delta_pct < -0.5:
                world_dir = "tightening"

    # cross-commodity comparison: pick the runner-up by |MoM %|.
    runner_up = sorted(
        ((c, abs(float(latest[US_COLS[c][1]]))) for c in moms if c != dominant),
        key=lambda x: -x[1],
    )[0][0] if len(moms) > 1 else dominant
    ru_lvl_col, ru_mom_col = US_COLS[runner_up]
    ru_world_col = WORLD_COLS[runner_up]
    ru_lvl = float(latest[ru_lvl_col])
    ru_mom = float(latest[ru_mom_col])

    summary = (
        f"In the {latest['release_label']} WASDE, U.S. {dominant} ending stocks "
        f"came in at {latest_lvl:,.0f} million bushels, "
        f"{'up' if latest_mom > 0 else 'down'} {abs(latest_mom):.1f}% from the prior release. "
        f"U.S. {runner_up} ending stocks stood at {ru_lvl:,.0f} mbu "
        f"({'up' if ru_mom > 0 else 'down'} {abs(ru_mom):.1f}% MoM), "
        f"with the world {dominant} balance reading as {world_dir}."
    )

    return {
        "dominant_us_commodity": dominant,
        "dominant_us_latest_mbu": round(latest_lvl, 0),
        "dominant_us_mom_pct": round(latest_mom, 2),
        "dominant_world_direction": world_dir,
        "report": summary,
        "as_of_release_month": latest["release_label"],
    }


def render_evidence(rows: list[dict], gt: dict) -> str:
    """Restate every CSV cell the rule consulted, verbatim, so the auditor's
    D1/D2 gates can ground every numeric token in the CSV.
    """
    latest = rows[-1]
    prior = rows[-2] if len(rows) >= 2 else None
    period = gt["as_of_release_month"]

    def _verbatim(col: str, row: dict | None) -> str:
        if row is None:
            return "(blank)"
        raw = row.get(col)
        return "(blank)" if raw in (None, "") else str(raw)

    lines = [
        f"# GT evidence -- USDA WASDE crop-balance brief {period}",
        "",
        "Derived deterministically from the latest row of "
        "`timeseries.csv` per the rule in `environment/session_brief.md`.",
        f"Cross-reference the WASDE PDF at `gt_source/{period}.pdf` "
        "(U.S. Wheat Supply and Use table on p11; U.S. Feed Grain and Corn "
        "Supply and Use on p12; U.S. Soybeans and Products Supply and Use "
        "on p15; World Wheat / Corn / Soybean Supply and Use on p18 / p22 "
        "/ p28 plus continuation pages for the latest projection).",
        "Note: this PDF is the GT source for the "
        f"{period} instance and is NOT visible to the agent at query time.",
        "",
        "## Latest CSV row anchors (verbatim CSV cells)",
        "",
        f"- release_label: `{_verbatim('release_label', latest)}`",
        f"- marketing_year: `{_verbatim('marketing_year', latest)}`",
        f"- corn_us_ending_stocks_mbu: `{_verbatim('corn_us_ending_stocks_mbu', latest)}`",
        f"- corn_us_ending_stocks_mom_pct: `{_verbatim('corn_us_ending_stocks_mom_pct', latest)}`",
        f"- soybeans_us_ending_stocks_mbu: `{_verbatim('soybeans_us_ending_stocks_mbu', latest)}`",
        f"- soybeans_us_ending_stocks_mom_pct: `{_verbatim('soybeans_us_ending_stocks_mom_pct', latest)}`",
        f"- wheat_us_ending_stocks_mbu: `{_verbatim('wheat_us_ending_stocks_mbu', latest)}`",
        f"- wheat_us_ending_stocks_mom_pct: `{_verbatim('wheat_us_ending_stocks_mom_pct', latest)}`",
        f"- corn_world_ending_stocks_mmt: `{_verbatim('corn_world_ending_stocks_mmt', latest)}`",
        f"- soybeans_world_ending_stocks_mmt: `{_verbatim('soybeans_world_ending_stocks_mmt', latest)}`",
        f"- wheat_world_ending_stocks_mmt: `{_verbatim('wheat_world_ending_stocks_mmt', latest)}`",
        "",
        "## Prior CSV row anchors (for world-stocks direction)",
        "",
        f"- release_label: `{_verbatim('release_label', prior)}`",
        f"- corn_world_ending_stocks_mmt: `{_verbatim('corn_world_ending_stocks_mmt', prior)}`",
        f"- soybeans_world_ending_stocks_mmt: `{_verbatim('soybeans_world_ending_stocks_mmt', prior)}`",
        f"- wheat_world_ending_stocks_mmt: `{_verbatim('wheat_world_ending_stocks_mmt', prior)}`",
        "",
        "## Field derivation",
        "",
        f"- `dominant_us_commodity` -> `{gt['dominant_us_commodity']}` "
        "(argmax of |MoM %| among corn / soybeans / wheat on the latest row; "
        "ties within 0.5 pp broken by canonical-season preference)",
        f"- `dominant_us_latest_mbu` -> `{gt['dominant_us_latest_mbu']}`",
        f"- `dominant_us_mom_pct` -> `{gt['dominant_us_mom_pct']}`",
        f"- `dominant_world_direction` -> `{gt['dominant_world_direction']}` "
        "(latest vs prior row world ending stocks for the dominant commodity, "
        "+/-0.5% dead-band; stocks growing = `loosening`, shrinking = "
        "`tightening`)",
        f"- `as_of_release_month` -> `{period}`",
        "- `report` -> templated from the four fields above plus one "
        "runner-up commodity for cross-commodity comparison.",
    ]
    return "\n".join(lines) + "\n"


def render_question(template: str, period: str, long_label: str) -> str:
    return (
        template
        .replace("{{period_label}}", period)
        .replace("{{month_label_long}}", long_label)
    )


def _step_gt() -> int:
    if not INSTANCES_DIR.exists():
        print("no instances/ yet; run `format.py timeseries` first.")
        return 1
    template = (ENV / "question_template.md").read_text(encoding="utf-8")
    n = 0
    for inst in sorted(INSTANCES_DIR.iterdir()):
        if not inst.is_dir():
            continue
        csv_path = inst / "timeseries.csv"
        if not csv_path.exists():
            continue
        with csv_path.open() as f:
            rows = list(csv.DictReader(f))
        if not rows:
            continue
        gt = derive_gt(rows)
        period = inst.name
        # Long label e.g. "May 2024"
        try:
            y, m = period.split("-")
            from datetime import date as _date
            long_label = month_label_long(_date(int(y), int(m), 1))
        except ValueError:
            long_label = period
        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2) + "\n")
        ev_text = render_evidence(rows, gt)
        # Append narrative-extract block (verbatim/drivers/risks/outlook).
        src_text, src_pages = load_source_text(GT_SOURCE / f"{period}.pdf")
        if src_text:
            ev_text = ev_text.rstrip() + "\n\n" + build_narrative_md_block(
                f"gt_source/{period}.pdf", src_text, pages=src_pages,
            )
        (inst / "gt_evidence.md").write_text(ev_text)
        (inst / "question.md").write_text(render_question(template, period, long_label))
        n += 1
    print(f"wrote GT + question + evidence for {n} instances")
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
