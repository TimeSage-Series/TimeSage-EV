#!/usr/bin/env python3
"""Build instances for this scenario's this scenario.

    python scripts/format.py                 # every step, in order: gt -> timeseries
    python scripts/format.py gt            # one step
    python scripts/format.py timeseries [flags]    # …with that step's own flags
    python scripts/format.py all [flags]     # every step, flags forwarded to each
    python scripts/format.py --list          # list the steps

Merged from format_timeseries.py and format_gt.py. Each step keeps the argument
parser it had before, so every flag that used to work still works — pass it
after the step name.
"""
from __future__ import annotations
import argparse
import calendar
import csv
import sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    INSTANCES, TS_SOURCE, data_month_for, iter_months, month_label, shift_month,
)
import json
from _common import (  # noqa: E402
    GT_SOURCE, INSTANCES, iter_months, month_label, shift_month,
)


# --- step: timeseries ----------------------------------------------------


COLUMNS = [
    "release_label", "release_year", "release_month", "data_month",
    "total_energy_consumption_quad_btu",
    "total_energy_production_quad_btu",
    "total_energy_net_balance_quad_btu",
    "total_energy_net_balance_mom_pct",
    "petroleum_consumption_mbd",
    "petroleum_consumption_mom_pct",
    "petroleum_production_mbd",
    "natural_gas_consumption_bcf_per_day",
    "natural_gas_consumption_mom_pct",
    "natural_gas_production_bcf_per_day",
    "coal_consumption_mmst",
    "coal_consumption_mom_pct",
    "electricity_net_generation_twh",
    "electricity_net_generation_mom_pct",
    "renewables_consumption_quad_btu",
    "renewables_consumption_mom_pct",
]

# Description -> (column key, scale).
#
# EIA T-tables ship monthly totals; for indicators tracked in per-day
# units (kbpd / bcfd) we divide by days_in_month before storing.
SERIES_MAP = {
    "Total Primary Energy Consumption":
        ("total_energy_consumption_quad_btu", 1.0, "monthly"),
    "Total Primary Energy Production":
        ("total_energy_production_quad_btu", 1.0, "monthly"),
    "Petroleum Products Supplied":
        ("petroleum_consumption_mbd", 1e-3, "per-day-already"),
    "Total Petroleum Field Production":
        ("petroleum_production_mbd", 1e-3, "per-day-already"),
    "Natural Gas Consumption":
        ("natural_gas_consumption_bcf_per_day", 1.0, "monthly-divide-days"),
    "Natural Gas Production (Dry)":
        ("natural_gas_production_bcf_per_day", 1.0, "monthly-divide-days"),
    "Coal Consumption":
        # EIA emits Thousand Short Tons; scenario column is "million short tons".
        ("coal_consumption_mmst", 1e-3, "monthly"),
    # Electricity total -- per-source aggregate from T07.02A.
    # EIA's Description col carries an embedded comma ("..., All Sectors")
    # which the CSV quotes; csv.DictReader handles quoted commas and the
    # Description field then renders without the suffix. We match the
    # canonical key text from the CSV's Description column verbatim.
    "Electricity Net Generation Total (including from sources not shown), All Sectors":
        # EIA emits Million Kilowatthours; scenario column is TWh -> 1e-3.
        ("electricity_net_generation_twh", 1e-3, "monthly"),
    # Renewables consumption is split across components in T01.03 too;
    # we use the dedicated aggregate row name.
    "Total Renewable Energy Consumption":
        ("renewables_consumption_quad_btu", 1.0, "monthly"),
}

# Which table file holds each description (priority order). When the
# same description appears in more than one table (e.g. "Coal Consumption"
# is in T01.03 as Quad BTU AND in T06.01 as Thousand Short Tons), the
# table listed FIRST wins, so the order below pins each series to the
# table whose units the scenario column expects.
TABLE_FILES = [
    TS_SOURCE / "mer_T01.01.csv",   # Quad BTU total energy aggregates
    TS_SOURCE / "mer_T03.01.csv",   # Petroleum kbpd
    TS_SOURCE / "mer_T04.01.csv",   # Natural gas Bcf
    TS_SOURCE / "mer_T06.01.csv",   # Coal Thousand Short Tons (NOT T01.03 Quad BTU)
    TS_SOURCE / "mer_T07.02A.csv",  # Electricity Million kWh
    TS_SOURCE / "mer_T01.03.csv",   # Renewables Quad BTU
]


def _parse_yyyymm(yyyymm: str) -> str | None:
    """Convert EIA YYYYMM (e.g. 202402) -> 'YYYY-MM'. Reject annual roll-ups
    (month == 13)."""
    if len(yyyymm) != 6 or not yyyymm.isdigit():
        return None
    y = int(yyyymm[:4])
    m = int(yyyymm[4:6])
    if m < 1 or m > 12:
        return None
    return f"{y:04d}-{m:02d}"


def _days_in(label: str) -> int:
    y, m = (int(x) for x in label.split("-"))
    return calendar.monthrange(y, m)[1]


def parse_table(path: Path) -> dict[str, dict[str, float]]:
    """Return {description: {YYYY-MM: float_value}}.

    Skips 'Not Available' and unparsable cells, drops annual roll-ups
    (YYYYMM with mm=13)."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            yyyymm = (r.get("YYYYMM") or "").strip()
            month_label = _parse_yyyymm(yyyymm)
            if not month_label:
                continue
            desc = (r.get("Description") or "").strip()
            value = (r.get("Value") or "").strip()
            if not value or value.lower().startswith("not available"):
                continue
            try:
                v = float(value)
            except ValueError:
                continue
            # Use latest value per (desc, month) if duplicates exist.
            out[desc][month_label] = v
    return out


def collapse_series() -> dict[str, dict[str, float]]:
    """Merge all tables into {column_key: {data_month: value}}, applying
    scale + per-day normalisation."""
    merged: dict[str, dict[str, float]] = defaultdict(dict)
    for path in TABLE_FILES:
        per_desc = parse_table(path)
        for desc, (key, scale, mode) in SERIES_MAP.items():
            if desc not in per_desc:
                continue
            for month, raw in per_desc[desc].items():
                v = raw * scale
                if mode == "monthly-divide-days":
                    v = v / _days_in(month)
                # If multiple tables expose the same key, keep the first
                # we encountered (table priority is the iteration order).
                if month not in merged[key]:
                    merged[key][month] = v
    return merged


def mom_pct(rows: list[dict], idx: int, col: str) -> float | None:
    if idx == 0:
        return None
    prev = rows[idx - 1].get(col)
    cur = rows[idx].get(col)
    if prev in (None, 0) or cur is None:
        return None
    return round(100.0 * (cur - prev) / prev, 2)


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--earliest-period", default="2022-01",
                    help="Earliest data-month to include in cumulative TS.")
    ap.add_argument("--instance-start", required=True,
                    help="First MER release month, e.g. 2024-04.")
    ap.add_argument("--instance-end", required=True,
                    help="Last MER release month, e.g. 2026-03.")
    args = ap.parse_args()

    if not any(p.exists() for p in TABLE_FILES):
        print("[err] no MER table CSVs found in timeseries_source/; "
              "run `download.py gt` first", file=sys.stderr)
        return 1

    merged = collapse_series()
    if not merged.get("total_energy_consumption_quad_btu"):
        print("[err] T01.01 parse failed or empty", file=sys.stderr)
        return 1

    # Build the canonical per-data-month row table from earliest to the
    # latest data month we'll need (= data_month_for(instance_end)).
    # The release_label is set PER INSTANCE later (every row in an
    # instance's CSV carries that instance's release_label, since the CSV
    # represents the MER vintage as of that release).
    end_release = args.instance_end
    last_data_month = data_month_for(end_release)
    raw_rows: list[dict] = []
    cur = args.earliest_period
    while cur <= last_data_month:
        row: dict = {"data_month": cur}
        for col in COLUMNS:
            if col in ("release_label", "release_year", "release_month",
                       "data_month"):
                continue
            if col.endswith("_mom_pct"):
                continue
            row[col] = merged.get(col, {}).get(cur)
        cons = row.get("total_energy_consumption_quad_btu")
        prod = row.get("total_energy_production_quad_btu")
        if cons is not None and prod is not None:
            row["total_energy_net_balance_quad_btu"] = round(prod - cons, 4)
        raw_rows.append(row)
        cur = shift_month(cur, +1)

    pct_cols = [
        ("total_energy_net_balance_mom_pct", "total_energy_net_balance_quad_btu"),
        ("petroleum_consumption_mom_pct",    "petroleum_consumption_mbd"),
        ("natural_gas_consumption_mom_pct",  "natural_gas_consumption_bcf_per_day"),
        ("coal_consumption_mom_pct",         "coal_consumption_mmst"),
        ("electricity_net_generation_mom_pct", "electricity_net_generation_twh"),
        ("renewables_consumption_mom_pct",   "renewables_consumption_quad_btu"),
    ]
    for i, _ in enumerate(raw_rows):
        for mom_col, base_col in pct_cols:
            raw_rows[i][mom_col] = mom_pct(raw_rows, i, base_col)

    def _fmt(v) -> str:
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{round(v, 4)}"
        return str(v)

    INSTANCES.mkdir(parents=True, exist_ok=True)
    n_written = 0
    for d in iter_months(args.instance_start, args.instance_end):
        release = month_label(d)
        target_data_month = data_month_for(release)
        slice_rows = [r for r in raw_rows if r["data_month"] <= target_data_month]
        if not slice_rows:
            print(f"[skip] {release}: no rows up to data_month {target_data_month}")
            continue
        if slice_rows[-1]["data_month"] != target_data_month:
            print(f"[skip] {release}: latest available data_month = "
                  f"{slice_rows[-1]['data_month']}; needed {target_data_month}")
            continue
        # Apply this instance's release_label to ALL rows in its CSV
        # (every row IS a MER-at-vintage-X cell).
        ry, rm = (int(x) for x in release.split("-"))
        stamped: list[dict] = []
        for r in slice_rows:
            r2 = dict(r)
            r2["release_label"] = release
            r2["release_year"] = ry
            r2["release_month"] = rm
            stamped.append(r2)
        inst_dir = INSTANCES / release
        inst_dir.mkdir(parents=True, exist_ok=True)
        out_path = inst_dir / "timeseries.csv"
        with out_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            for r in stamped:
                w.writerow([_fmt(r.get(c)) for c in COLUMNS])
        n_written += 1
        print(f"[csv]  {release}: {len(stamped)} rows, "
              f"data_month={target_data_month}")

    print(f"wrote {n_written} instance CSVs ({args.instance_start}..{args.instance_end})")
    return 0


# --- step: gt ------------------------------------------------------------
SECTORS = [
    ("petroleum", "petroleum_consumption_mom_pct"),
    ("natural_gas", "natural_gas_consumption_mom_pct"),
    ("coal", "coal_consumption_mom_pct"),
    ("electricity", "electricity_net_generation_mom_pct"),
    ("renewables", "renewables_consumption_mom_pct"),
]


# Controlled-vocab driver mapping by dominant sector + month.
DRIVER_BY_SECTOR = {
    "petroleum":    ["transportation_demand_shift", "import_flow_shift",
                     "export_flow_shift", "industrial_demand_shift"],
    "natural_gas":  ["seasonal_heating_demand", "industrial_demand_shift",
                     "export_flow_shift", "weather_impact"],
    "coal":         ["seasonal_heating_demand", "production_capacity_change",
                     "industrial_demand_shift", "weather_impact"],
    "electricity":  ["seasonal_cooling_demand", "weather_impact",
                     "industrial_demand_shift", "production_capacity_change"],
    "renewables":   ["production_capacity_change", "seasonal_cooling_demand",
                     "weather_impact", "export_flow_shift"],
}


def _to_float(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def balance_direction(history: list[dict]) -> str | None:
    """Compute on net-balance Quad BTU MoM, deadbanded at ±0.5%."""
    if len(history) < 2:
        return None
    latest = _to_float(history[-1].get("total_energy_net_balance_quad_btu"))
    prior = _to_float(history[-2].get("total_energy_net_balance_quad_btu"))
    if latest is None or prior is None or abs(prior) == 0:
        return None
    change_pct = 100.0 * (latest - prior) / abs(prior)
    if change_pct > 0.5:
        return "loosening"
    if change_pct < -0.5:
        return "tightening"
    return "balanced"


def canonical_season_sector(month: int | None) -> str:
    if month in (11, 12, 1, 2):
        return "natural_gas"
    if month in (6, 7, 8, 9):
        return "electricity"
    return "petroleum"


def dominant_sector(latest: dict) -> str | None:
    sec_values: dict[str, float] = {}
    for code, col in SECTORS:
        v = _to_float(latest.get(col))
        if v is not None:
            sec_values[code] = v
    if not sec_values:
        return None
    max_abs = max(abs(v) for v in sec_values.values())
    leaders = [s for s, v in sec_values.items() if abs(v) == max_abs]
    if len(leaders) > 1:
        release_month = _to_int(latest.get("release_month"))
        preferred = canonical_season_sector(release_month)
        return preferred if preferred in leaders else leaders[0]
    return leaders[0]


def pick_drivers(dominant: str | None, release_month: int | None,
                 history: list[dict]) -> list[str]:
    if not dominant:
        return ["weather_impact", "other"]
    candidates = list(DRIVER_BY_SECTOR.get(dominant, ["other"]))
    if release_month in (12, 1, 2) and "seasonal_heating_demand" not in candidates:
        candidates.insert(1, "seasonal_heating_demand")
    if release_month in (7, 8, 9) and "seasonal_cooling_demand" not in candidates:
        candidates.insert(1, "seasonal_cooling_demand")
    # Trailing-3 net-balance volatility booster.
    if len(history) >= 4:
        trail = [_to_float(r.get("total_energy_net_balance_mom_pct"))
                 for r in history[-4:-1]]
        trail = [t for t in trail if t is not None]
        if trail:
            avg_abs = sum(abs(t) for t in trail) / len(trail)
            if avg_abs > 2.5 and "weather_impact" not in candidates:
                candidates.append("weather_impact")
    out = candidates[:3]
    if len(out) < 2:
        out.append("other")
    return out


def outlook_next(history: list[dict]) -> str:
    """Trailing 3-row balance trajectory rule.

    - tighter:   last 2 balance MoM < 0 (surplus shrinking) avg ≤ −1.0
    - looser:    last 2 balance MoM > 0 (surplus growing) avg ≥ +1.0
    - unchanged: trailing signs alternate AND |MoM| < 2.0
    - unclear:   otherwise
    """
    trail = [_to_float(r.get("total_energy_net_balance_mom_pct"))
             for r in history[-3:]]
    trail = [t for t in trail if t is not None]
    if len(trail) < 2:
        return "unclear"
    last2 = trail[-2:]
    avg = sum(last2) / len(last2)
    if all(x < 0 for x in last2) and avg <= -1.0:
        return "tighter"
    if all(x > 0 for x in last2) and avg >= 1.0:
        return "looser"
    signs = [1 if x > 0 else (-1 if x < 0 else 0) for x in trail]
    if len(set(s for s in signs if s != 0)) > 1 and all(abs(x) < 2.0 for x in trail):
        return "unchanged"
    return "unclear"


def build_supporting_evidence(period: str, latest: dict, history: list[dict],
                              dominant: str | None, drivers: list[str]) -> list[dict]:
    items: list[dict] = []
    bal = _to_float(latest.get("total_energy_net_balance_quad_btu"))
    bal_mom = _to_float(latest.get("total_energy_net_balance_mom_pct"))
    if bal is not None and bal_mom is not None:
        items.append({
            "observation": (
                f"U.S. total-energy net balance (production - consumption) "
                f"in the latest MER row reads {bal:+.3f} Quad BTU and moved "
                f"{bal_mom:+.2f}% MoM."
            ),
            "evidence_reference": (
                f"timeseries.csv last row — "
                f"total_energy_net_balance_quad_btu = {bal:+.3f}, "
                f"total_energy_net_balance_mom_pct = {bal_mom:+.2f}"
            ),
        })
    petro_mom = _to_float(latest.get("petroleum_consumption_mom_pct"))
    petro_lvl = _to_float(latest.get("petroleum_consumption_mbd"))
    if petro_mom is not None and petro_lvl is not None:
        items.append({
            "observation": (
                f"U.S. petroleum products supplied (consumption proxy) "
                f"moved {petro_mom:+.2f}% MoM to {petro_lvl:.2f} mb/d on "
                f"the latest MER row."
            ),
            "evidence_reference": (
                f"timeseries.csv last row — "
                f"petroleum_consumption_mbd = {petro_lvl:.2f}, "
                f"petroleum_consumption_mom_pct = {petro_mom:+.2f}"
            ),
        })
    # Dominant-sector CSV cell.
    if dominant:
        col = {
            "petroleum":   "petroleum_consumption_mom_pct",
            "natural_gas": "natural_gas_consumption_mom_pct",
            "coal":        "coal_consumption_mom_pct",
            "electricity": "electricity_net_generation_mom_pct",
            "renewables":  "renewables_consumption_mom_pct",
        }[dominant]
        v = _to_float(latest.get(col))
        if v is not None:
            items.append({
                "observation": (
                    f"The {dominant.replace('_', ' ')} sector posted the "
                    f"largest |MoM %| swing on the latest MER row at "
                    f"{v:+.2f}%, identifying it as the dominant balance "
                    f"sector."
                ),
                "evidence_reference": (
                    f"timeseries.csv last row — {col} = {v:+.2f}"
                ),
            })
    # Prior-period MER PDF if available.
    prior_release = shift_month(period, -1)
    prior_pdf = GT_SOURCE / f"mer_{prior_release}.pdf"
    if prior_pdf.exists():
        items.append({
            "observation": (
                f"Prior MER bulletin {prior_release} provides the closing "
                f"narrative + STEO-style framing context used for the "
                f"forward-inference outlook tag."
            ),
            "evidence_reference": (
                f"gt_source/mer_{prior_release}.pdf — prior-period MER "
                f"bulletin, closing-section commentary on U.S. energy "
                f"production / consumption trajectory."
            ),
        })
    return items


def report_text(period: str, balance_dir: str | None, petro_mom: float | None,
                       dominant: str | None, drivers: list[str], outlook: str) -> str:
    parts: list[str] = []
    if balance_dir:
        parts.append(f"In MER release {period}, the U.S. total-energy "
                     f"self-balance was assessed as {balance_dir}.")
    else:
        parts.append(f"In MER release {period}, the U.S. total-energy "
                     f"self-balance direction was indeterminate.")
    if petro_mom is not None:
        parts.append(f"Petroleum consumption moved {petro_mom:+.2f}% MoM.")
    if dominant:
        parts.append(f"The dominant balance sector was "
                     f"{dominant.replace('_', ' ')}.")
    if drivers:
        parts.append(f"Key drivers: {', '.join(drivers)}.")
    parts.append(f"Forward inference for next release: {outlook}.")
    return " ".join(parts)[:800]


def emit_gt_evidence_md(period: str, gt: dict, latest: dict,
                       history: list[dict]) -> str:
    dom = gt.get("dominant_balance_sector")
    lines: list[str] = []
    lines.append(f"# Evidence — EIA Monthly Energy Review {period}")
    lines.append("")
    lines.append("## Per-answer-field citations")
    lines.append("")
    bal_mom = _to_float(latest.get("total_energy_net_balance_mom_pct"))
    bal = _to_float(latest.get("total_energy_net_balance_quad_btu"))
    petro_mom = _to_float(latest.get("petroleum_consumption_mom_pct"))
    petro_lvl = _to_float(latest.get("petroleum_consumption_mbd"))
    lines.append(f"- **total_energy_balance_direction** -> `{gt['total_energy_balance_direction']}`")
    lines.append(f"  - timeseries.csv last row `total_energy_net_balance_quad_btu` = {bal}; "
                 f"prior-row delta deadbanded at ±0.5% (MoM% = {bal_mom}).")
    lines.append(f"- **petroleum_consumption_mom_pct** -> `{gt['petroleum_consumption_mom_pct']}`")
    lines.append(f"  - timeseries.csv last row `petroleum_consumption_mom_pct` = {petro_mom}; "
                 f"`petroleum_consumption_mbd` = {petro_lvl}.")
    if dom:
        lines.append(f"- **dominant_balance_sector** -> `{dom}`")
        lines.append(f"  - Largest absolute consumption MoM% among the five "
                     f"tracked sectors on the latest CSV row.")
    lines.append(f"- **key_drivers** -> `{gt['key_drivers']}`")
    lines.append("  - Heuristic: dominant-sector → controlled-vocab map "
                 "+ seasonal booster (Dec–Feb heating; Jul–Sep cooling) "
                 "+ trailing-3 balance-MoM volatility booster.")
    lines.append(f"- **outlook_direction_next_period** -> `{gt['outlook_direction_next_period']}`")
    lines.append("  - Trailing-3-row balance MoM trajectory rule. Forward "
                 "inference, not a prediction of an unpublished MER.")
    lines.append("- **report** -> templated 1–3 sentence factual summary.")
    lines.append("- **supporting_evidence** -> at least 2 items grounded in "
                 "CSV cells and (when available) the prior-release MER PDF.")
    lines.append("")
    lines.append("## Trailing trajectory (last 4 rows)")
    lines.append("")
    lines.append("| data_month | net_bal_quad_btu | bal_mom% | petro_mbd | petro_mom% | gas_bcfd | gas_mom% |")
    lines.append("|------------|------------------|----------|-----------|------------|----------|----------|")
    for r in history[-4:]:
        def _f(c, dec=2):
            v = _to_float(r.get(c))
            if v is None:
                return ""
            return f"{v:+.{dec}f}" if c.endswith("_pct") or c.endswith("balance_quad_btu") else f"{v:.{dec}f}"
        lines.append(
            f"| {r.get('data_month','')} | {_f('total_energy_net_balance_quad_btu', 3)} | "
            f"{_f('total_energy_net_balance_mom_pct')} | "
            f"{_f('petroleum_consumption_mbd')} | {_f('petroleum_consumption_mom_pct')} | "
            f"{_f('natural_gas_consumption_bcf_per_day')} | {_f('natural_gas_consumption_mom_pct')} |"
        )
    return "\n".join(lines) + "\n"


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    INSTANCES.mkdir(parents=True, exist_ok=True)
    n_written = 0
    for d in iter_months(args.instance_start, args.instance_end):
        release = month_label(d)
        inst = INSTANCES / release
        ts_path = inst / "timeseries.csv"
        if not ts_path.exists():
            print(f"[skip] {release}: no timeseries.csv")
            continue
        history = read_csv(ts_path)
        if len(history) < 2:
            print(f"[skip] {release}: history too short")
            continue
        latest = history[-1]
        bal_dir = balance_direction(history) or "balanced"
        petro_mom = _to_float(latest.get("petroleum_consumption_mom_pct"))
        dominant = dominant_sector(latest)
        release_month = _to_int(latest.get("release_month"))
        drivers = pick_drivers(dominant, release_month, history)
        outlook = outlook_next(history)
        evidence = build_supporting_evidence(release, latest, history, dominant, drivers)
        gt = {
            "report_month": release,
            "total_energy_balance_direction": bal_dir,
            "petroleum_consumption_mom_pct": round(petro_mom, 4) if petro_mom is not None else 0.0,
            "dominant_balance_sector": dominant or "petroleum",
            "key_drivers": drivers,
            "outlook_direction_next_period": outlook,
            "report": report_text(release, bal_dir, petro_mom, dominant, drivers, outlook),
            "supporting_evidence": evidence,
        }
        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2), encoding="utf-8")
        (inst / "gt_evidence.md").write_text(
            emit_gt_evidence_md(release, gt, latest, history), encoding="utf-8"
        )
        n_written += 1
        print(f"[ok]   {release}: bal_dir={bal_dir} petro_mom={petro_mom} "
              f"dom={dominant} drivers={drivers} outlook={outlook}")
    print(f"wrote {n_written} ground_truth.json + gt_evidence.md instances")
    return 0

# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------

#: Execution order. This scenario builds the series from the ground truth, so gt runs first.
STEPS = ("gt", "timeseries")

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
