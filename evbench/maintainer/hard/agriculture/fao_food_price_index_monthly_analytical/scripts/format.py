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
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import INSTANCES, TS_SOURCE, iter_months, month_label  # noqa: E402
import json
from _common import (  # noqa: E402
    GT_SOURCE, INSTANCES, iter_months, long_month_label, month_label, prior_month,
)


# --- step: timeseries ----------------------------------------------------


COLUMNS = [
    "release_label", "release_year", "release_month",
    "fao_food_price_index", "fao_food_price_index_mom_pct",
    "fao_food_price_index_yoy_pct",
    "cereals_subindex", "cereals_subindex_mom_pct",
    "vegetable_oils_subindex", "vegetable_oils_subindex_mom_pct",
    "dairy_subindex", "dairy_subindex_mom_pct",
    "meat_subindex", "meat_subindex_mom_pct",
    "sugar_subindex", "sugar_subindex_mom_pct",
]


def _to_float(v: str) -> float | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_raw_csv(path: Path) -> dict[str, dict]:
    """Return {YYYY-MM: {fao_food_price_index, cereals_subindex, ...}}."""
    out: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    # Skip metadata rows; find the header row.
    header_idx = None
    for i, row in enumerate(rows[:8]):
        if row and row[0].strip().lower() == "date":
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError(f"could not locate header row in {path}")
    # We expect: Date, Food Price Index, Meat, Dairy, Cereals, Oils, Sugar
    # (columns 0..6). Trailing real-terms columns appear past col 6 but we
    # do not consume them.
    for row in rows[header_idx + 1:]:
        if not row:
            continue
        period = (row[0] or "").strip()
        if not period or len(period) != 7 or period[4] != "-":
            continue
        try:
            int(period[:4]); int(period[5:7])
        except ValueError:
            continue
        out[period] = {
            "fao_food_price_index":   _to_float(row[1]) if len(row) > 1 else None,
            "meat_subindex":          _to_float(row[2]) if len(row) > 2 else None,
            "dairy_subindex":         _to_float(row[3]) if len(row) > 3 else None,
            "cereals_subindex":       _to_float(row[4]) if len(row) > 4 else None,
            "vegetable_oils_subindex": _to_float(row[5]) if len(row) > 5 else None,
            "sugar_subindex":         _to_float(row[6]) if len(row) > 6 else None,
        }
    return out


def mom_pct(rows: list[dict], idx: int, col: str) -> float | None:
    if idx == 0:
        return None
    prev = rows[idx - 1].get(col)
    cur = rows[idx].get(col)
    if prev in (None, 0) or cur is None:
        return None
    return round(100.0 * (cur - prev) / prev, 2)


def yoy_pct(rows: list[dict], idx: int, col: str) -> float | None:
    if idx < 12:
        return None
    prev = rows[idx - 12].get(col)
    cur = rows[idx].get(col)
    if prev in (None, 0) or cur is None:
        return None
    return round(100.0 * (cur - prev) / prev, 2)


def _fmt(v) -> str:
    return "" if v is None else f"{v}"


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--earliest-period", default="2022-01")
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    raw_csv = TS_SOURCE / "food_price_indices_data.csv"
    if not raw_csv.exists():
        print(f"[err] missing {raw_csv}; run `download.py gt` first", file=sys.stderr)
        return 1

    raw = parse_raw_csv(raw_csv)
    earliest = args.earliest_period
    inst_end = args.instance_end
    # Keep periods from earliest through instance-end (inclusive).
    periods = sorted(p for p in raw if earliest <= p <= inst_end)
    if not periods:
        print(f"[err] no rows in CSV between {earliest} and {inst_end}", file=sys.stderr)
        return 1

    # Build a master row list ordered by period.
    rows: list[dict] = []
    for p in periods:
        rec = dict(raw[p])
        y, m = (int(x) for x in p.split("-"))
        rec["release_label"] = p
        rec["release_year"] = y
        rec["release_month"] = m
        rows.append(rec)

    # Compute MoM% and YoY% in place.
    for i, _ in enumerate(rows):
        rows[i]["fao_food_price_index_mom_pct"] = mom_pct(rows, i, "fao_food_price_index")
        rows[i]["fao_food_price_index_yoy_pct"] = yoy_pct(rows, i, "fao_food_price_index")
        for sub in ("cereals", "vegetable_oils", "dairy", "meat", "sugar"):
            rows[i][f"{sub}_subindex_mom_pct"] = mom_pct(rows, i, f"{sub}_subindex")

    INSTANCES.mkdir(parents=True, exist_ok=True)
    n_written = 0
    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        # Slice rows up through and including this period.
        keep_idx = [i for i, r in enumerate(rows) if r["release_label"] <= label]
        if not keep_idx:
            print(f"[skip] {label}: no rows in CSV at or before period")
            continue
        # Confirm this exact period is present (else don't create an instance).
        last_label = rows[keep_idx[-1]]["release_label"]
        if last_label != label:
            print(f"[skip] {label}: CSV has no row for this period (latest available: {last_label})")
            continue
        inst_dir = INSTANCES / label
        inst_dir.mkdir(parents=True, exist_ok=True)
        out_path = inst_dir / "timeseries.csv"
        with out_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            for i in keep_idx:
                r = rows[i]
                w.writerow([_fmt(r.get(c)) for c in COLUMNS])
        n_written += 1
        print(f"[csv]  {label}: {len(keep_idx)} rows")

    print(f"wrote {n_written} instance CSVs ({args.instance_start}..{args.instance_end})")
    return 0


# --- step: gt ------------------------------------------------------------
SUBINDEX_CODES = ["cereals", "vegetable_oils", "dairy", "meat", "sugar"]


def _to_float__gt(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def headline_direction(mom: float | None) -> str:
    if mom is None:
        return "flat"
    if mom > 0.3:
        return "up"
    if mom < -0.3:
        return "down"
    return "flat"


def dominant_subindex(latest: dict, headline_dir: str) -> str | None:
    """Same-sign / largest-abs / ≥0.5pp rule; falls back to largest-abs."""
    sub_values: dict[str, float] = {}
    for code in SUBINDEX_CODES:
        v = _to_float__gt(latest.get(f"{code}_subindex_mom_pct"))
        if v is not None:
            sub_values[code] = v
    if not sub_values:
        return None
    matching: dict[str, float] = {}
    if headline_dir == "up":
        matching = {k: v for k, v in sub_values.items() if v >= 0.5}
    elif headline_dir == "down":
        matching = {k: v for k, v in sub_values.items() if v <= -0.5}
    if matching:
        return max(matching.items(), key=lambda kv: (abs(kv[1]), kv[0]))[0]
    return max(sub_values.items(), key=lambda kv: (abs(kv[1]), kv[0]))[0]


# Heuristic driver mapping by dominant sub-index + season.
# Each chosen driver MUST be substantiated by a supporting_evidence item;
# the evidence builder below maps each chosen driver back to a CSV cell.
DRIVER_BY_SUBINDEX = {
    "cereals":         ["weather_impact", "harvest_progress",
                        "geopolitical_supply_risk", "export_restrictions"],
    "vegetable_oils":  ["biofuel_demand", "import_demand_shift",
                        "energy_input_cost", "weather_impact"],
    "dairy":           ["seasonality", "import_demand_shift",
                        "energy_input_cost", "fx_effect"],
    "meat":            ["seasonality", "import_demand_shift",
                        "harvest_progress", "energy_input_cost"],
    "sugar":           ["weather_impact", "biofuel_demand",
                        "harvest_progress", "energy_input_cost"],
}


def pick_drivers(dominant: str | None, headline_dir: str,
                 release_month: int, history: list[dict]) -> list[str]:
    if not dominant:
        return ["seasonality", "other"]
    candidates = list(DRIVER_BY_SUBINDEX.get(dominant, ["other"]))
    # Seasonality booster: northern-hemisphere harvest months Jul-Sep.
    if release_month in (7, 8, 9) and "harvest_progress" not in candidates:
        candidates.insert(1, "harvest_progress")
    if release_month in (11, 12, 1, 2) and "seasonality" not in candidates:
        candidates.insert(1, "seasonality")
    # Geopolitical-risk booster if the trailing-3 headline MoM volatility
    # is unusually high (>1.5 pp average abs MoM).
    if len(history) >= 4:
        trail = [_to_float__gt(r.get("fao_food_price_index_mom_pct"))
                 for r in history[-4:-1]]
        trail = [t for t in trail if t is not None]
        if trail:
            avg_abs = sum(abs(t) for t in trail) / len(trail)
            if avg_abs > 1.5 and "geopolitical_supply_risk" not in candidates:
                candidates.append("geopolitical_supply_risk")
    # Keep top 3 to satisfy minItems=2 maxItems=5 with room.
    out = candidates[:3]
    if len(out) < 2:
        out.append("other")
    return out


def outlook_next(history: list[dict]) -> str:
    """Trailing-3-month MoM trajectory heuristic.

    - rising:    last 2 MoM > 0 and average >= +0.5
    - easing:    last 2 MoM < 0 and average <= -0.5
    - sideways:  trailing MoM signs alternate and |MoM| < 1.0
    - unclear:   otherwise
    """
    trail = [_to_float__gt(r.get("fao_food_price_index_mom_pct"))
             for r in history[-3:]]
    trail = [t for t in trail if t is not None]
    if len(trail) < 2:
        return "unclear"
    last2 = trail[-2:]
    avg = sum(last2) / len(last2)
    if all(x > 0 for x in last2) and avg >= 0.5:
        return "rising"
    if all(x < 0 for x in last2) and avg <= -0.5:
        return "easing"
    # Alternating-sign sideways check.
    signs = [1 if x > 0 else (-1 if x < 0 else 0) for x in trail]
    if len(set(s for s in signs if s != 0)) > 1 and all(abs(x) < 1.0 for x in trail):
        return "sideways"
    return "unclear"


def build_supporting_evidence(period: str, latest: dict, history: list[dict],
                              dominant: str | None, drivers: list[str]) -> list[dict]:
    """Build at least 2 evidence items grounded in CSV cells / prior cards."""
    items: list[dict] = []
    # 1) Headline MoM CSV cell.
    headline_mom = _to_float__gt(latest.get("fao_food_price_index_mom_pct"))
    headline_lvl = _to_float__gt(latest.get("fao_food_price_index"))
    if headline_mom is not None and headline_lvl is not None:
        items.append({
            "observation": (
                f"Headline FAO Food Price Index moved {headline_mom:+.2f}% MoM "
                f"in {period}, reading {headline_lvl:.1f} on the 2014-2016=100 base."
            ),
            "evidence_reference": (
                f"timeseries.csv row {period} — "
                f"fao_food_price_index_mom_pct = {headline_mom:+.2f}, "
                f"fao_food_price_index = {headline_lvl:.1f}"
            ),
        })
    # 2) Dominant sub-index MoM CSV cell.
    if dominant:
        sub_mom = _to_float__gt(latest.get(f"{dominant}_subindex_mom_pct"))
        sub_lvl = _to_float__gt(latest.get(f"{dominant}_subindex"))
        if sub_mom is not None and sub_lvl is not None:
            items.append({
                "observation": (
                    f"The {dominant.replace('_', ' ')} sub-index "
                    f"moved {sub_mom:+.2f}% MoM in {period}, reading "
                    f"{sub_lvl:.1f}, which dominated the headline move."
                ),
                "evidence_reference": (
                    f"timeseries.csv row {period} — "
                    f"{dominant}_subindex_mom_pct = {sub_mom:+.2f}, "
                    f"{dominant}_subindex = {sub_lvl:.1f}"
                ),
            })
    # 3) Prior-period snapshot card (gt_source HTML), if a prior period
    # exists in CSV history.
    if len(history) >= 2:
        prior = history[-2]
        prior_label = prior.get("release_label")
        prior_mom = _to_float__gt(prior.get("fao_food_price_index_mom_pct"))
        if prior_label and prior_mom is not None:
            items.append({
                "observation": (
                    f"Prior month {prior_label} had a headline MoM of "
                    f"{prior_mom:+.2f}%, providing trajectory context for "
                    f"the current-period analytical inference."
                ),
                "evidence_reference": (
                    f"gt_source/fao_fpi_{prior_label}.html — "
                    f"prior-period headline-and-subindex snapshot card "
                    f"(fao_food_price_index_mom_pct = {prior_mom:+.2f})"
                ),
            })
    # 4) Driver-supporting evidence: cite a CSV cell that justifies a driver.
    if drivers and dominant:
        # Cite the cumulative trailing window via a CSV header pointer.
        items.append({
            "observation": (
                f"Driver inference (chosen: {', '.join(drivers)}) leans on "
                f"the trailing FAO FPI sub-index trajectory and the canonical "
                f"sub-index-to-driver mapping documented in the session brief."
            ),
            "evidence_reference": (
                f"timeseries.csv columns — {dominant}_subindex, "
                f"{dominant}_subindex_mom_pct (trailing 3 rows ending {period})"
            ),
        })
    return items


def report_text(period: str, headline_dir: str, mom: float | None,
                       dominant: str | None, drivers: list[str],
                       outlook: str) -> str:
    parts: list[str] = []
    if mom is not None:
        parts.append(
            f"In {period}, the FAO Food Price Index moved {headline_dir} by "
            f"{mom:+.2f}% MoM."
        )
    else:
        parts.append(f"In {period}, the FAO Food Price Index headline was {headline_dir}.")
    if dominant:
        parts.append(
            f"The move was dominated by the {dominant.replace('_', ' ')} sub-index."
        )
    if drivers:
        parts.append(f"Key drivers in scope: {', '.join(drivers)}.")
    parts.append(f"Forward inference for next month: {outlook}.")
    summary = " ".join(parts)
    return summary[:800]


def emit_prior_card_html(period: str, row: dict) -> str:
    """A simple HTML card that summarizes a single period's FAO FPI readings.

    Used as the prior-period reference the agent can consult under
    /root/gt_source/. The card intentionally restates only the FACTS of
    that period (no forward outlook) so it does not leak GT for any
    future period that cites it.
    """
    fpi = _to_float__gt(row.get("fao_food_price_index"))
    cereals = _to_float__gt(row.get("cereals_subindex"))
    oils = _to_float__gt(row.get("vegetable_oils_subindex"))
    dairy = _to_float__gt(row.get("dairy_subindex"))
    meat = _to_float__gt(row.get("meat_subindex"))
    sugar = _to_float__gt(row.get("sugar_subindex"))
    fpi_mom = _to_float__gt(row.get("fao_food_price_index_mom_pct"))
    cereals_mom = _to_float__gt(row.get("cereals_subindex_mom_pct"))
    oils_mom = _to_float__gt(row.get("vegetable_oils_subindex_mom_pct"))
    dairy_mom = _to_float__gt(row.get("dairy_subindex_mom_pct"))
    meat_mom = _to_float__gt(row.get("meat_subindex_mom_pct"))
    sugar_mom = _to_float__gt(row.get("sugar_subindex_mom_pct"))

    def _fmt(v):
        return f"{v:.1f}" if isinstance(v, float) else "n/a"

    def _fmtp(v):
        return f"{v:+.2f}%" if isinstance(v, float) else "n/a"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FAO Food Price Index — {period} snapshot</title>
</head>
<body>
<h1>FAO Food Price Index — {long_month_label(period)} ({period}) snapshot card</h1>
<p>This card restates the published FAO FPI readings for {period} on the
2014-2016=100 base, for use as prior-period narrative context. It carries
no forward outlook commentary about future months.</p>
<table>
<thead>
<tr><th>series</th><th>level</th><th>MoM%</th></tr>
</thead>
<tbody>
<tr><td>headline FAO Food Price Index</td><td>{_fmt(fpi)}</td><td>{_fmtp(fpi_mom)}</td></tr>
<tr><td>cereals sub-index</td>           <td>{_fmt(cereals)}</td><td>{_fmtp(cereals_mom)}</td></tr>
<tr><td>vegetable oils sub-index</td>    <td>{_fmt(oils)}</td>   <td>{_fmtp(oils_mom)}</td></tr>
<tr><td>dairy sub-index</td>             <td>{_fmt(dairy)}</td>  <td>{_fmtp(dairy_mom)}</td></tr>
<tr><td>meat sub-index</td>              <td>{_fmt(meat)}</td>   <td>{_fmtp(meat_mom)}</td></tr>
<tr><td>sugar sub-index</td>             <td>{_fmt(sugar)}</td>  <td>{_fmtp(sugar_mom)}</td></tr>
</tbody>
</table>
<p>Source: FAO World Food Situation — Food Price Indices (nominal). Card
generated from the same CSV bundle exposed at
<code>/root/timeseries.csv</code>.</p>
</body>
</html>
"""


def emit_gt_evidence_md(period: str, gt: dict, latest: dict,
                       history: list[dict]) -> str:
    dominant = gt.get("dominant_subindex_contributor")
    lines: list[str] = []
    lines.append(f"# Evidence — FAO Food Price Index {period}")
    lines.append("")
    lines.append("## Per-answer-field citations")
    lines.append("")
    fpi_mom = _to_float__gt(latest.get("fao_food_price_index_mom_pct"))
    fpi_lvl = _to_float__gt(latest.get("fao_food_price_index"))
    lines.append(f"- **headline_index_direction** -> `{gt['headline_index_direction']}`")
    lines.append(f"  - Latest CSV row `fao_food_price_index_mom_pct` = {fpi_mom}; "
                 f"±0.3% deadband applied.")
    lines.append(f"- **headline_index_mom_pct** -> `{gt['headline_index_mom_pct']}`")
    lines.append(f"  - timeseries.csv row {period} `fao_food_price_index_mom_pct` = {fpi_mom}; "
                 f"`fao_food_price_index` = {fpi_lvl}.")
    if dominant:
        sub_mom = _to_float__gt(latest.get(f"{dominant}_subindex_mom_pct"))
        sub_lvl = _to_float__gt(latest.get(f"{dominant}_subindex"))
        lines.append(f"- **dominant_subindex_contributor** -> `{dominant}`")
        lines.append(f"  - timeseries.csv row {period} `{dominant}_subindex_mom_pct` = {sub_mom}; "
                     f"`{dominant}_subindex` = {sub_lvl}. Same-sign / largest-|MoM| selection.")
    lines.append(f"- **key_drivers** -> `{gt['key_drivers']}`")
    lines.append("  - Heuristic: dominant sub-index → driver vocab map "
                 "+ seasonal booster + headline-volatility booster (≥1.5pp trailing-3 |MoM| avg).")
    lines.append(f"- **outlook_direction_next_period** -> `{gt['outlook_direction_next_period']}`")
    lines.append("  - Trailing-3-month MoM trajectory rule. Forward inference, "
                 "not a prediction of an unpublished bulletin.")
    lines.append(f"- **report** -> templated 1–3 sentence factual summary.")
    lines.append("- **supporting_evidence** -> at least 2 items grounded in "
                 "CSV cells and (when available) a prior-month gt_source HTML card.")
    lines.append("")
    lines.append("## Trailing trajectory (last 4 rows)")
    lines.append("")
    lines.append("| period | fpi | fpi_mom% | cereals_mom% | oils_mom% | dairy_mom% | meat_mom% | sugar_mom% |")
    lines.append("|--------|-----|----------|--------------|-----------|------------|-----------|------------|")
    for r in history[-4:]:
        def _f(c):
            v = _to_float__gt(r.get(c))
            return f"{v:+.2f}" if isinstance(v, float) and c.endswith("_pct") else (f"{v:.1f}" if isinstance(v, float) else "")
        lines.append(
            f"| {r.get('release_label','')} | {_f('fao_food_price_index')} | "
            f"{_f('fao_food_price_index_mom_pct')} | {_f('cereals_subindex_mom_pct')} | "
            f"{_f('vegetable_oils_subindex_mom_pct')} | {_f('dairy_subindex_mom_pct')} | "
            f"{_f('meat_subindex_mom_pct')} | {_f('sugar_subindex_mom_pct')} |"
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

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    INSTANCES.mkdir(parents=True, exist_ok=True)

    # Pre-pass: emit prior-period snapshot cards for ALL periods present
    # in the LAST instance's timeseries (longest history). The agent will
    # be served only the strictly-prior subset at session time; for build
    # purposes we generate them all.
    last_label = month_label(list(iter_months(args.instance_start, args.instance_end))[-1])
    last_csv = INSTANCES / last_label / "timeseries.csv"
    if not last_csv.exists():
        print(f"[err] missing {last_csv}; run `format.py timeseries` first", file=sys.stderr)
        return 1
    all_rows = read_csv(last_csv)
    written_cards = 0
    for r in all_rows:
        label = r.get("release_label")
        if not label:
            continue
        out = GT_SOURCE / f"fao_fpi_{label}.html"
        out.write_text(emit_prior_card_html(label, r), encoding="utf-8")
        written_cards += 1
    print(f"[gt-cards] wrote {written_cards} prior-period HTML cards to gt_source/")

    # Per-instance GT + evidence.
    n_written = 0
    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        inst = INSTANCES / label
        ts_path = inst / "timeseries.csv"
        if not ts_path.exists():
            print(f"[skip] {label}: no timeseries.csv")
            continue
        history = read_csv(ts_path)
        if not history:
            print(f"[skip] {label}: empty timeseries.csv")
            continue
        latest = history[-1]
        if latest.get("release_label") != label:
            print(f"[skip] {label}: last CSV row label mismatch "
                  f"({latest.get('release_label')})")
            continue
        mom = _to_float__gt(latest.get("fao_food_price_index_mom_pct"))
        h_dir = headline_direction(mom)
        dominant = dominant_subindex(latest, h_dir)
        release_month = int(label.split("-")[1])
        drivers = pick_drivers(dominant, h_dir, release_month, history)
        outlook = outlook_next(history)
        evidence = build_supporting_evidence(label, latest, history, dominant, drivers)
        gt = {
            "report_month": label,
            "headline_index_direction": h_dir,
            "headline_index_mom_pct": round(mom, 4) if mom is not None else 0.0,
            "dominant_subindex_contributor": dominant or "cereals",
            "key_drivers": drivers,
            "outlook_direction_next_period": outlook,
            "report": report_text(label, h_dir, mom, dominant, drivers, outlook),
            "supporting_evidence": evidence,
        }
        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2), encoding="utf-8")
        (inst / "gt_evidence.md").write_text(
            emit_gt_evidence_md(label, gt, latest, history), encoding="utf-8"
        )
        n_written += 1
        print(f"[ok]   {label}: dir={h_dir} mom={mom} dom={dominant} drivers={drivers} outlook={outlook}")

    print(f"wrote {n_written} ground_truth.json + gt_evidence.md instances")
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
