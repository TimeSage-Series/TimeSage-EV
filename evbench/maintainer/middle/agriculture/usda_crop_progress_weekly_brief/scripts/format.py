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
import datetime as dt
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, INSTANCES, usda_week_label, parse_label  # noqa: E402
from _common import GT_SOURCE, INSTANCES, usda_week_label, parse_label  # noqa: E402
MAINTAINER_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(MAINTAINER_ROOT / "lib"))
from narrative_extract import build_narrative_md_block, load_source_text  # noqa: E402


# --- step: timeseries ----------------------------------------------------

SERIES_FILES = [
    "corn_planted_pct.json", "corn_emerged_pct.json", "corn_harvested_pct.json",
    "corn_condition_good_pct.json",
    "soybeans_planted_pct.json", "soybeans_harvested_pct.json",
    "soybeans_condition_good_pct.json",
    "wheat_winter_condition_good_pct.json",
]

COLS = [
    "week_ending", "usda_year", "usda_week",
    "corn_planted_pct", "corn_emerged_pct", "corn_harvested_pct", "corn_condition_good_pct",
    "soybeans_planted_pct", "soybeans_harvested_pct", "soybeans_condition_good_pct",
    "wheat_winter_condition_good_pct",
]


def to_float(s):
    if s is None: return None
    s = s.replace(",", "").strip()
    if not s or s == "(D)": return None
    try: return float(s)
    except ValueError: return None


def load_series(fname: str) -> dict[tuple[int, int], dict]:
    """Return {(year, week): {week_ending, value}}."""
    path = TS_SOURCE / fname
    if not path.exists(): return {}
    payload = json.loads(path.read_text())
    out: dict[tuple[int, int], dict] = {}
    for row in payload.get("data", []):
        # reference_period_desc is "WEEK #21" etc.
        m = re.search(r"WEEK\s*#?(\d+)", row.get("reference_period_desc", ""))
        if not m: continue
        wk = int(m.group(1))
        yr = int(row.get("year") or 0)
        v = to_float(row.get("Value"))
        if v is None: continue
        out[(yr, wk)] = {
            "week_ending": row.get("week_ending"),
            "value": v,
        }
    return out


def _canonical_week_ending(yr: int, wk: int) -> str:
    """Compute week_ending deterministically from (usda_year, usda_week).

    NASS Crop Progress weeks end on Sunday and use ISO-style week numbering
    where week 1 is the week containing the year's first Sunday in 4 days.
    Trust the (yr, wk) key over any source-provided week_ending, since
    upstream NASS JSON occasionally mislabels cross-year rows (e.g. a row
    keyed (2022, 47) but stamped week_ending=2021-11-28).
    """
    # ISO weekday 7 = Sunday. fromisocalendar gives Mon..Sun of ISO week.
    try:
        return dt.date.fromisocalendar(yr, wk, 7).isoformat()
    except ValueError:
        return ""


def build_table():
    col_data: dict[str, dict[tuple[int, int], dict]] = {}
    keys: set[tuple[int, int]] = set()
    for f in SERIES_FILES:
        col = f.replace(".json", "")
        col_data[col] = load_series(f)
        keys.update(col_data[col].keys())
    rows = []
    for (yr, wk) in sorted(keys):
        row = {"usda_year": yr, "usda_week": wk}
        for col, d in col_data.items():
            cell = d.get((yr, wk))
            row[col] = round(cell["value"], 1) if cell else None
        row["week_ending"] = _canonical_week_ending(yr, wk)
        rows.append(row)
    return rows


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True, help="YYYY-wkWW inclusive")
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    rows = build_table()
    by_key = {(r["usda_year"], r["usda_week"]): r for r in rows}
    ordered = [(r["usda_year"], r["usda_week"]) for r in rows]

    sy, sw = parse_label(args.instance_start); ey, ew = parse_label(args.instance_end)
    for (yr, wk) in ordered:
        if (yr, wk) < (sy, sw) or (yr, wk) > (ey, ew): continue
        idx = ordered.index((yr, wk))
        window = [by_key[k] for k in ordered[: idx + 1]]
        label = usda_week_label(yr, wk)
        out_dir = INSTANCES / label
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "timeseries.csv").open("w", newline="") as f:
            w_ = csv.DictWriter(f, fieldnames=COLS)
            w_.writeheader()
            for r in window: w_.writerow({k: r.get(k) for k in COLS})
        print(f"[ok]  {label}: {len(window)} weeks", flush=True)


# --- step: gt ------------------------------------------------------------
ACTIVITY_COL = {
    "corn_planted_pct":              "corn_planting",
    "corn_emerged_pct":              "corn_emergence",
    "corn_harvested_pct":            "corn_harvest",
    "corn_condition_good_pct":       "corn_condition_report",
    "soybeans_planted_pct":          "soybean_planting",
    "soybeans_harvested_pct":        "soybean_harvest",
    "soybeans_condition_good_pct":   "soybean_condition_report",
    "wheat_winter_condition_good_pct": "wheat_condition_report",
}


def to_float__gt(s):
    if s in (None, "", "None"): return None
    try: return float(s)
    except ValueError: return None


def process(label: str) -> tuple[dict, str] | None:
    inst = INSTANCES / label
    ts_csv = inst / "timeseries.csv"
    if not ts_csv.exists(): return None
    rows = list(csv.DictReader(ts_csv.open()))
    if len(rows) < 2: return None
    last = rows[-1]; prior = rows[-2]
    yr, wk = parse_label(label)

    best_col = None; best_change = -1.0; best_last = None
    for col, _activity in ACTIVITY_COL.items():
        cur = to_float__gt(last.get(col)); pr = to_float__gt(prior.get(col))
        if cur is None: continue
        if pr is None: pr = 0.0
        change = abs(cur - pr)
        if change > best_change:
            best_change = change; best_col = col; best_last = cur

    if best_col is None:
        return None
    dominant = ACTIVITY_COL[best_col]
    cur = to_float__gt(last.get(best_col)); pr = to_float__gt(prior.get(best_col))
    wow = round(cur - (pr or 0.0), 1)

    # 5-yr-avg comparison
    prior_year_vals = []
    for r in rows[:-1]:
        if to_float__gt(r.get("usda_week")) == wk and to_float__gt(r.get("usda_year")) != yr:
            v = to_float__gt(r.get(best_col))
            if v is not None: prior_year_vals.append(v)
    if len(prior_year_vals) >= 3:
        avg = sum(prior_year_vals) / len(prior_year_vals)
        if cur - avg >  5: direction = "ahead"
        elif cur - avg < -5: direction = "behind"
        else: direction = "on_pace"
    else:
        direction = "on_pace"

    gt = {
        "dominant_crop_activity": dominant,
        "latest_value_pct": round(cur, 1),
        "wow_change_pp": wow,
        "vs_5yr_avg_direction": direction,
        "as_of_week": label,
        "report": (
            f"{best_col.replace('_', ' ').replace(' pct', '').title()} at "
            f"{round(cur,1)}% in week {label} ({wow:+.1f} pp WoW, {direction} vs 5-year same-week average)."
        ),
    }

    md = [
        f"# Evidence — Crop Progress {label} (week ending {last.get('week_ending')})\n",
        f"Source: `gt_source/{label}.pdf` (USDA NASS Crop Progress weekly report)\n",
        f"## Current-issue deterministic snapshot\n",
        f"- **dominant_crop_activity** -> `{dominant}` (max WoW |Δ| over 8 NASS series; "
        f"chosen column: `{best_col}`)",
        f"- **latest_value_pct** -> `{gt['latest_value_pct']}` (latest row {best_col})",
        f"- **wow_change_pp** -> `{wow}` (latest {cur} vs prior {pr})",
        f"- **vs_5yr_avg_direction** -> `{direction}` "
        f"(comparison values: {prior_year_vals[:5]})",
        f"- **report** -> graded against the Crop Progress PDF page-1 commentary.",
    ]
    # Append verbatim + driver/risk/outlook trigger sentences from the PDF.
    pdf_path = GT_SOURCE / f"{label}.pdf"
    src_text, pages = load_source_text(pdf_path)
    if src_text:
        md.append(build_narrative_md_block(
            source_ref=f"gt_source/{label}.pdf",
            source_text=src_text,
            pages=pages,
            verbatim_label=f"Verbatim Crop Progress narrative (page 1)",
            max_verbatim_chars=2500,
        ))
    return gt, "\n".join(md)


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    sy, sw = parse_label(args.instance_start); ey, ew = parse_label(args.instance_end)
    for inst_dir in sorted(INSTANCES.iterdir()):
        label = inst_dir.name
        try: yr, wk = parse_label(label)
        except ValueError: continue
        if (yr, wk) < (sy, sw) or (yr, wk) > (ey, ew): continue
        out = process(label)
        if out is None: continue
        gt, ev = out
        (inst_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        (inst_dir / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: act={gt['dominant_crop_activity']} "
              f"val={gt['latest_value_pct']}% Δ={gt['wow_change_pp']}pp", flush=True)

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
