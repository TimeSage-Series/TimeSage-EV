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
from pathlib import Path
import json
import shutil
import sys
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
ENV_DIR = ROOT / "environment"
GT_SOURCE = ROOT / "gt_source"
MAINTAINER_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(MAINTAINER_ROOT / "lib"))
from narrative_extract import build_narrative_md_block, load_source_text  # noqa: E402


# --- step: timeseries ----------------------------------------------------




ROOT = _scenario_data_dir(__file__)
RAW_DIR = ROOT / "timeseries_source"
INSTANCES_DIR = ROOT / "instances"

SERIES = {
    "PCU482111482111": "rail_ppi",
    "PCU484121484121": "general_truck_ppi",
    "PCU483111483111": "deep_sea_ppi",
    "PCU481111481111": "scheduled_air_ppi",
    "PCU488488": "transport_support_ppi",
}

YOY_OUT = {
    "rail_ppi": "rail_ppi_yoy_pct",
    "general_truck_ppi": "general_truck_ppi_yoy_pct",
    "deep_sea_ppi": "deep_sea_ppi_yoy_pct",
    "scheduled_air_ppi": "scheduled_air_ppi_yoy_pct",
    "transport_support_ppi": "transport_support_ppi_yoy_pct",
}

COLUMNS = [
    "release_label", "data_month",
    "rail_ppi", "general_truck_ppi", "deep_sea_ppi", "scheduled_air_ppi", "transport_support_ppi",
    "general_truck_ppi_mom_pct", "general_truck_ppi_yoy_pct",
    "rail_ppi_yoy_pct", "deep_sea_ppi_yoy_pct", "scheduled_air_ppi_yoy_pct", "transport_support_ppi_yoy_pct",
]

EARLIEST_RAW_PERIOD = "2022-01"

# Per scenario.yaml instance_window.
INSTANCE_START = "2024-05"
INSTANCE_END = "2026-04"


def _parse_period(date_str: str) -> str:
    return date_str[:7]


def _round_or_blank(x, ndigits: int = 2) -> str:
    if x is None:
        return ""
    return f"{round(x, ndigits)}"


def load_series(sid: str) -> dict[str, float]:
    p = RAW_DIR / f"{sid}.csv"
    if not p.exists():
        raise FileNotFoundError(f"{p} missing — run download_fred_ppi.py first")
    out: dict[str, float] = {}
    with p.open() as f:
        rdr = csv.reader(f)
        header = next(rdr)
        # FRED CSV header is [observation_date, <SID>]; tolerate either column order.
        date_idx = header.index("observation_date") if "observation_date" in header else 0
        val_idx = 1 if len(header) > 1 else 1
        for row in rdr:
            try:
                period = _parse_period(row[date_idx])
                val = float(row[val_idx])
            except (ValueError, IndexError):
                continue
            out[period] = val
    return out


def _step_timeseries() -> int:
    series_by_name: dict[str, dict[str, float]] = {}
    for sid, name in SERIES.items():
        series_by_name[name] = load_series(sid)

    # Union of all periods, intersected with >= EARLIEST_RAW_PERIOD.
    all_periods: set[str] = set()
    for d in series_by_name.values():
        all_periods.update(d.keys())
    periods = sorted(p for p in all_periods if p >= EARLIEST_RAW_PERIOD)

    # Build enriched rows.
    enriched: list[dict] = []
    for i, period in enumerate(periods):
        row: dict = {"release_label": period, "data_month": period}
        # Levels.
        for name in series_by_name:
            row[name] = series_by_name[name].get(period)
        # general_truck_ppi MoM.
        if i >= 1:
            prev = periods[i - 1]
            prv_val = series_by_name["general_truck_ppi"].get(prev)
            cur_val = row["general_truck_ppi"]
            if prv_val and cur_val is not None and prv_val != 0:
                row["general_truck_ppi_mom_pct"] = 100.0 * (cur_val - prv_val) / prv_val
            else:
                row["general_truck_ppi_mom_pct"] = None
        else:
            row["general_truck_ppi_mom_pct"] = None
        # YoY for each mode.
        if i >= 12:
            ya_period = periods[i - 12]
            for name in series_by_name:
                ya_val = series_by_name[name].get(ya_period)
                cur_val = row[name]
                if ya_val and cur_val is not None and ya_val != 0:
                    row[YOY_OUT[name]] = 100.0 * (cur_val - ya_val) / ya_val
                else:
                    row[YOY_OUT[name]] = None
        else:
            for name in series_by_name:
                row[YOY_OUT[name]] = None
        enriched.append(row)

    INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for end_idx, end_row in enumerate(enriched):
        period = end_row["release_label"]
        if period < INSTANCE_START or period > INSTANCE_END:
            continue
        inst_dir = INSTANCES_DIR / period
        inst_dir.mkdir(parents=True, exist_ok=True)
        csv_path = inst_dir / "timeseries.csv"
        with csv_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for r in enriched[: end_idx + 1]:
                out_row = {
                    "release_label": r["release_label"],
                    "data_month": r["data_month"],
                }
                for name in SERIES.values():
                    out_row[name] = _round_or_blank(r.get(name), 3)
                out_row["general_truck_ppi_mom_pct"] = _round_or_blank(
                    r.get("general_truck_ppi_mom_pct"), 2)
                for name, yoy_col in YOY_OUT.items():
                    out_row[yoy_col] = _round_or_blank(r.get(yoy_col), 2)
                w.writerow(out_row)
        written += 1
        print(f"  wrote {csv_path}")
    print(f"`format.py timeseries`: wrote {written} instances")
    return 0


# --- step: gt ------------------------------------------------------------
MODE_LABELS = {
    "rail_ppi_yoy_pct": "rail_freight",
    "general_truck_ppi_yoy_pct": "general_freight_trucking",
    "deep_sea_ppi_yoy_pct": "deep_sea_freight",
    "scheduled_air_ppi_yoy_pct": "scheduled_air",
    "transport_support_ppi_yoy_pct": "transport_support",
}

MONTH_LONG = {
    "01": "January", "02": "February", "03": "March", "04": "April",
    "05": "May", "06": "June", "07": "July", "08": "August",
    "09": "September", "10": "October", "11": "November", "12": "December",
}


def _parse_or_none(s):
    if s in (None, ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def classify_mom_direction(mom):
    if mom is None:
        return "flat"
    if mom > 0.5:
        return "rising"
    if mom < -0.5:
        return "falling"
    return "flat"


def leading_mode(latest_row: dict) -> str:
    # argmax over 5 mode YoY columns; alpha tiebreak on the mode label.
    yoy_pairs: list[tuple[float, str]] = []
    for col, label in MODE_LABELS.items():
        v = _parse_or_none(latest_row.get(col))
        if v is None:
            continue
        yoy_pairs.append((v, label))
    if not yoy_pairs:
        # First 12 months have no YoY — should not occur for the declared window
        # (starts 2024-05; cumulative goes back to 2022-01).
        return "general_freight_trucking"
    # Sort: highest YoY first; ties broken alphabetically by label.
    yoy_pairs.sort(key=lambda x: (-x[0], x[1]))
    return yoy_pairs[0][1]


def derive_gt_from_row(latest: dict) -> dict:
    value = _parse_or_none(latest.get("general_truck_ppi"))
    mom = _parse_or_none(latest.get("general_truck_ppi_mom_pct"))
    yoy = _parse_or_none(latest.get("general_truck_ppi_yoy_pct"))
    direction = classify_mom_direction(mom)
    leader = leading_mode(latest)
    leader_col = next(c for c, l in MODE_LABELS.items() if l == leader)
    leader_yoy = _parse_or_none(latest.get(leader_col))

    period = latest["release_label"]
    mom_word = "up" if (mom is not None and mom > 0) else "down" if (mom is not None and mom < 0) else "flat"
    yoy_word = "up" if (yoy is not None and yoy > 0) else "down" if (yoy is not None and yoy < 0) else "flat"

    summary = (
        f"In the {period} BLS PPI release, the headline general-freight-trucking "
        f"index read {value:.1f}, "
        + (f"{mom_word} {abs(mom):.2f}% month-over-month " if mom is not None else "with MoM not computable ")
        + (f"and {yoy_word} {abs(yoy):.2f}% year-over-year. " if yoy is not None else "and YoY not computable. ")
        + f"Under the ±0.5% MoM dead-band the headline reads as {direction}. "
        + (f"The leading transportation mode by YoY was {leader} (+{leader_yoy:.2f}%)."
           if leader_yoy is not None and leader_yoy >= 0
           else (f"The leading transportation mode by YoY was {leader} ({leader_yoy:+.2f}%)."
                 if leader_yoy is not None else
                 f"The leading transportation mode by YoY was {leader}."))
    )

    return {
        "as_of_release_month": period,
        "headline_ppi_level": round(value, 2) if value is not None else 0,
        "headline_mom_pct": round(mom, 2) if mom is not None else 0.0,
        "headline_yoy_pct": round(yoy, 2) if yoy is not None else 0.0,
        "headline_mom_direction": direction,
        "leading_mode_by_yoy": leader,
        "report": summary,
    }


def render_question(period: str) -> str:
    template = (ENV_DIR / "question_template.md").read_text()
    y, m = period.split("-")
    month_long = f"{MONTH_LONG[m]} {y}"
    return (template
            .replace("{{period_label}}", period)
            .replace("{{month_label_long}}", month_long))


def _step_gt() -> int:
    if not INSTANCES_DIR.exists():
        print("no instances/ yet; run `format.py timeseries` first.")
        return 1
    schema = (ENV_DIR / "answer_schema.json").read_bytes()
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
        latest = rows[-1]
        gt = derive_gt_from_row(latest)
        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2) + "\n")
        (inst / "answer_schema.json").write_bytes(schema)
        (inst / "question.md").write_text(render_question(inst.name))
        ev_lines = [
            f"# GT evidence for {inst.name}",
            "",
            f"Source: `gt_source/{inst.name}.pdf` "
            "(BLS Producer Price Index detailed news release PDF; "
            "NOT visible to the agent at query time)",
            "",
            "## Current-issue deterministic snapshot",
            f"- **headline_ppi_level** -> `{gt['headline_ppi_level']}` "
            f"(latest row `general_truck_ppi`, FRED PCU484121484121)",
            f"- **headline_mom_pct** -> `{gt['headline_mom_pct']:+.2f}%` "
            f"(`general_truck_ppi_mom_pct`)",
            f"- **headline_yoy_pct** -> `{gt['headline_yoy_pct']:+.2f}%` "
            f"(`general_truck_ppi_yoy_pct`)",
            f"- **headline_mom_direction** -> `{gt['headline_mom_direction']}` "
            f"(±0.5% dead-band on MoM)",
            f"- **leading_mode_by_yoy** -> `{gt['leading_mode_by_yoy']}` "
            f"(argmax across 5 mode YoY columns; alphabetical tiebreak)",
            "",
            "## Source",
            "",
            f"Derived from `timeseries.csv` latest row (FRED-mirrored BLS PPI 5-mode panel).",
        ]
        pdf_path = GT_SOURCE / f"{inst.name}.pdf"
        src_text, pages = load_source_text(pdf_path)
        if src_text:
            ev_lines.append(build_narrative_md_block(
                source_ref=f"gt_source/{inst.name}.pdf",
                source_text=src_text,
                pages=pages,
                verbatim_label="Verbatim BLS PPI release excerpt (opening narrative)",
                max_verbatim_chars=2500,
            ))
        (inst / "gt_evidence.md").write_text("\n".join(ev_lines) + "\n")
        n += 1
    print(f"wrote GT for {n} instances")
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
