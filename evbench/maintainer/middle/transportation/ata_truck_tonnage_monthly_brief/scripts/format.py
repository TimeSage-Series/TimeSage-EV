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
GT_SOURCE = ROOT / "gt_source"
MAINTAINER_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(MAINTAINER_ROOT / "lib"))
from narrative_extract import build_narrative_md_block, load_source_text  # noqa: E402


# --- step: timeseries ----------------------------------------------------




ROOT = _scenario_data_dir(__file__)
RAW_CSV = ROOT / "timeseries_source" / "truckd11.csv"
INSTANCES_DIR = ROOT / "instances"

COLUMNS = [
    "release_label", "data_month",
    "tonnage_index_sa", "tonnage_index_mom_pct", "tonnage_index_yoy_pct",
    "rolling6_mean", "rolling6_dev_pct",
]

EARLIEST_RAW_PERIOD = "2022-01"


def _parse_period(date_str: str) -> str:
    # FRED format is YYYY-MM-DD; we only need YYYY-MM.
    return date_str[:7]


def _round_or_blank(x: float | None, ndigits: int = 2) -> str:
    if x is None:
        return ""
    return f"{round(x, ndigits)}"


def _step_timeseries() -> int:
    if not RAW_CSV.exists():
        print(f"missing raw CSV: {RAW_CSV}. Run download_fred_truckd11.py first.")
        return 1

    # Read FRED CSV.
    raw_rows: list[tuple[str, float]] = []
    with RAW_CSV.open() as f:
        reader = csv.reader(f)
        header = next(reader)
        date_col = header.index("DATE") if "DATE" in header else 0
        val_col = header.index("TRUCKD11") if "TRUCKD11" in header else 1
        for row in reader:
            try:
                period = _parse_period(row[date_col])
                val = float(row[val_col])
            except (ValueError, IndexError):
                continue
            if period < EARLIEST_RAW_PERIOD:
                continue
            raw_rows.append((period, val))
    raw_rows.sort(key=lambda x: x[0])

    # Build enriched rows.
    enriched: list[dict] = []
    for i, (period, val) in enumerate(raw_rows):
        prev_val = raw_rows[i - 1][1] if i >= 1 else None
        prior_year_val = raw_rows[i - 12][1] if i >= 12 else None
        mom = (
            round(100.0 * (val - prev_val) / prev_val, 2)
            if prev_val not in (None, 0)
            else None
        )
        yoy = (
            round(100.0 * (val - prior_year_val) / prior_year_val, 2)
            if prior_year_val not in (None, 0)
            else None
        )
        if i >= 5:
            window = [raw_rows[j][1] for j in range(i - 5, i + 1)]
            rolling6 = round(sum(window) / 6.0, 3)
            rolling6_dev = round(100.0 * (val - rolling6) / rolling6, 2) if rolling6 else None
        else:
            rolling6 = None
            rolling6_dev = None
        enriched.append({
            "release_label": period,
            "data_month": period,
            "tonnage_index_sa": round(val, 3),
            "tonnage_index_mom_pct": mom,
            "tonnage_index_yoy_pct": yoy,
            "rolling6_mean": rolling6,
            "rolling6_dev_pct": rolling6_dev,
        })

    INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
    for end_idx, end_row in enumerate(enriched):
        period = end_row["release_label"]
        inst_dir = INSTANCES_DIR / period
        inst_dir.mkdir(parents=True, exist_ok=True)
        csv_path = inst_dir / "timeseries.csv"
        with csv_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            for r in enriched[: end_idx + 1]:
                w.writerow({
                    "release_label": r["release_label"],
                    "data_month": r["data_month"],
                    "tonnage_index_sa": _round_or_blank(r["tonnage_index_sa"], 3),
                    "tonnage_index_mom_pct": _round_or_blank(r["tonnage_index_mom_pct"], 2),
                    "tonnage_index_yoy_pct": _round_or_blank(r["tonnage_index_yoy_pct"], 2),
                    "rolling6_mean": _round_or_blank(r["rolling6_mean"], 3),
                    "rolling6_dev_pct": _round_or_blank(r["rolling6_dev_pct"], 2),
                })
        print(f"  wrote {csv_path}")
    return 0


# --- step: gt ------------------------------------------------------------
def classify_direction(mom: float | None, yoy: float | None) -> str:
    if mom is not None and mom > 0.5:
        return "expanding"
    if mom is not None and mom < -0.5:
        return "contracting"
    if yoy is not None and yoy > 1.0:
        return "expanding"
    if yoy is not None and yoy < -1.0:
        return "contracting"
    return "flat"


def rolling6_phrase(dev: float | None) -> str:
    if dev is None:
        return "with the 6-month rolling average not yet computable"
    if dev > 1.0:
        return f"running roughly {dev:+.1f}% above the 6-month rolling average"
    if dev < -1.0:
        return f"running roughly {dev:+.1f}% below the 6-month rolling average"
    return "broadly in line with the 6-month rolling average"


def _parse_or_none(s: str | None) -> float | None:
    if s in (None, ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def derive_gt(rows: list[dict]) -> dict:
    latest = rows[-1]
    value = _parse_or_none(latest.get("tonnage_index_sa"))
    mom = _parse_or_none(latest.get("tonnage_index_mom_pct"))
    yoy = _parse_or_none(latest.get("tonnage_index_yoy_pct"))
    dev = _parse_or_none(latest.get("rolling6_dev_pct"))

    direction = classify_direction(mom, yoy)
    period = latest["release_label"]

    mom_word = "up" if (mom is not None and mom > 0) else "down" if (mom is not None and mom < 0) else "flat"
    yoy_word = "up" if (yoy is not None and yoy > 0) else "down" if (yoy is not None and yoy < 0) else "flat"

    summary = (
        f"In the {period} ATA Truck Tonnage Index release, the SA index read "
        f"{value:.1f}, "
        + (f"{mom_word} {abs(mom):.1f}% month-over-month " if mom is not None else "with MoM not computable ")
        + (f"and {yoy_word} {abs(yoy):.1f}% year-over-year. " if yoy is not None else "and YoY not computable. ")
        + f"On the ±0.5% MoM dead-band rule the freight market reads as {direction}, "
        f"{rolling6_phrase(dev)}."
    )

    return {
        "as_of_release_month": period,
        "tonnage_index_value": round(value, 2) if value is not None else 0,
        "mom_pct": round(mom, 2) if mom is not None else 0.0,
        "yoy_pct": round(yoy, 2) if yoy is not None else 0.0,
        "freight_market_direction": direction,
        "report": summary,
    }


def _step_gt() -> int:
    if not INSTANCES_DIR.exists():
        print("no instances/ yet; run `format.py timeseries` first.")
        return 1
    n = 0
    for inst in sorted(INSTANCES_DIR.iterdir()):
        if not inst.is_dir():
            continue
        csv_path = inst / "timeseries.csv"
        if not csv_path.exists():
            continue
        with csv_path.open() as f:
            rows = list(csv.DictReader(f))
        gt = derive_gt(rows)
        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2) + "\n")
        ev_lines = [
            f"# GT evidence for {inst.name}",
            "",
            f"Source: `gt_source/{inst.name}.html` "
            f"(ATA Truck Tonnage Index press release; NOT visible to the agent at query time)",
            "",
            "## Current-issue deterministic snapshot",
            f"- **tonnage_index_value** -> `{gt['tonnage_index_value']}` "
            f"(latest CSV row `tonnage_index_sa`, FRED TRUCKD11)",
            f"- **mom_pct** -> `{gt['mom_pct']:+.2f}%` "
            f"(latest CSV row `tonnage_index_mom_pct`)",
            f"- **yoy_pct** -> `{gt['yoy_pct']:+.2f}%` "
            f"(latest CSV row `tonnage_index_yoy_pct`)",
            f"- **freight_market_direction** -> `{gt['freight_market_direction']}` "
            f"(±0.5% MoM dead-band rule with ±1% YoY tiebreaker)",
            "",
            "## Source",
            "",
            f"Derived from `timeseries.csv` latest row (FRED TRUCKD11 SA index).",
            f"Cross-reference the ATA press release HTML at `gt_source/{inst.name}.html` "
            "for narrative quotes. The current release-month press release is the "
            "narrative GT and is NOT visible to the agent at query time.",
        ]
        html_path = GT_SOURCE / f"{inst.name}.html"
        src_text, _ = load_source_text(html_path)
        if src_text:
            ev_lines.append(build_narrative_md_block(
                source_ref=f"gt_source/{inst.name}.html",
                source_text=src_text,
                pages=None,
                verbatim_label="Verbatim ATA press-release excerpt",
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
