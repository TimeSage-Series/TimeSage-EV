"""Build the 24 instance directories for
bea_pce_inflation_monthly_attribution.

Computes YoY inflation rates for headline and core PCE, classifies
drivers and outlook, and writes per-instance artifacts.
"""
from __future__ import annotations

import csv
import json
import shutil
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    ENV, FED_TARGET, GT_SOURCE, INSTANCES, QUERY_MONTHS, SERIES, TS_SOURCE,
)


def read_series(sid: str) -> dict[str, float]:
    src = TS_SOURCE / f"{sid}.csv"
    out: dict[str, float] = {}
    with src.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("observation_date", "").strip()
            v = row.get(sid, "").strip()
            if not d or not v:
                continue
            try:
                out[d[:7]] = float(v)
            except ValueError:
                pass
    return out


def yoy_pct(cur: float | None, year_ago: float | None) -> float | None:
    if cur is None or year_ago is None or year_ago == 0:
        return None
    return (cur - year_ago) / year_ago * 100.0


def shift_month(period: str, months: int) -> str:
    y, m = period.split("-")
    yi = int(y); mi = int(m)
    mi += months
    while mi <= 0:
        yi -= 1
        mi += 12
    while mi > 12:
        yi += 1
        mi -= 12
    return f"{yi:04d}-{mi:02d}"


def _fmt_num(x, max_decimals: int) -> str:
    if x in (None, ""):
        return ""
    s = f"{x:.{max_decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def classify_drivers(period: str, headline_yoy: float, core_yoy: float,
                     prev_headline: float | None, prev_core: float | None) -> list[str]:
    month = int(period.split("-")[1])
    drivers: list[str] = []

    # Headline vs core gap signals goods/energy/food vs services
    if headline_yoy > core_yoy + 0.3:
        # Headline pressured above core: goods/energy/food
        drivers.append("energy_volatility")
    if headline_yoy < core_yoy - 0.3:
        # Core sticky, headline easing: goods disinflation
        drivers.append("goods_disinflation")
    if core_yoy >= 2.5:
        drivers.append("services_inflation")
        drivers.append("shelter_costs")
    if core_yoy < 2.0 and headline_yoy < 2.2:
        drivers.append("goods_disinflation")

    # Wage growth as background for sticky core
    if core_yoy > 2.5 and core_yoy >= (prev_core or 0) - 0.1:
        drivers.append("wage_growth")

    # Food/energy: tied to month-of-year + headline-vs-core gap
    if headline_yoy - core_yoy > 0.5:
        drivers.append("food_costs")
    if month in (3, 4, 5, 9, 10) and abs(headline_yoy - core_yoy) > 0.4:
        drivers.append("durable_goods")

    # Supply chain — sharp deceleration / acceleration vs prior month
    if prev_headline is not None and abs(headline_yoy - prev_headline) > 0.3:
        drivers.append("supply_chain")

    # FX passthrough / tariff effects (used sparingly)
    if abs(headline_yoy - 2.0) > 0.6 and month in (1, 7):
        drivers.append("fx_passthrough")
    if abs(headline_yoy - core_yoy) > 0.7 and "tariff_effect" not in drivers and month % 4 == 0:
        drivers.append("tariff_effect")

    # Deduplicate, cap at 5
    seen = set()
    out: list[str] = []
    for d in drivers:
        if d not in seen:
            seen.add(d)
            out.append(d)
        if len(out) >= 5:
            break
    if len(out) < 2:
        out.append("other")
    return out[:5]


def classify_outlook(period: str, headline_yoy: float, prev_headline: float | None,
                     core_yoy: float, prev_core: float | None) -> str:
    """Forward direction from MoM-style YoY-pp delta in headline + core."""
    if prev_headline is None or prev_core is None:
        return "unclear"
    h_delta = headline_yoy - prev_headline
    c_delta = core_yoy - prev_core
    # Disinflating: BOTH headline and core easing
    if h_delta < -0.05 and c_delta <= 0.0:
        return "disinflating"
    # Accelerating: BOTH rising
    if h_delta > 0.05 and c_delta >= 0.0:
        return "accelerating"
    # Unchanged: both within small band
    if abs(h_delta) <= 0.05 and abs(c_delta) <= 0.05:
        return "unchanged"
    return "unclear"


def render_timeseries_csv(inst_dir: Path, periods_all: list[str],
                          headline: dict, core: dict,
                          headline_yoy: dict, core_yoy: dict,
                          cur_period: str) -> None:
    out = inst_dir / "timeseries.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["period", "headline_pce_yoy_pct", "core_pce_yoy_pct",
                    "headline_pce_index", "core_pce_index"])
        for p in periods_all:
            if p > cur_period:
                break
            w.writerow([
                p,
                _fmt_num(headline_yoy.get(p), 3),
                _fmt_num(core_yoy.get(p), 3),
                _fmt_num(headline.get(p), 4),
                _fmt_num(core.get(p), 4),
            ])


def render_ground_truth(period: str, headline_yoy: float, core_yoy: float,
                        prev_headline: float | None, prev_core: float | None,
                        drivers: list[str], outlook: str,
                        prior_period: str | None) -> dict:
    headline_mom_pp = (
        round(headline_yoy - prev_headline, 3)
        if prev_headline is not None else 0.0
    )
    vs_target_pp = round(headline_yoy - FED_TARGET, 3)
    drivers_str = ", ".join(d.replace("_", " ") for d in drivers)
    summary = (
        f"In {period}, headline PCE inflation ran at {headline_yoy:.2f}% YoY "
        f"(core {core_yoy:.2f}% YoY); the MoM YoY-pp delta in headline was "
        f"{headline_mom_pp:+.2f} pp, and the headline gap to the Fed's 2% target "
        f"is {vs_target_pp:+.2f} pp. Drivers: {drivers_str}. Forward outlook: {outlook}."
    )
    evid: list[dict] = []
    if prior_period and prev_headline is not None:
        evid.append({
            "observation": (
                f"Prior month {prior_period} headline PCE YoY was {prev_headline:.2f}%, "
                f"giving the current month a +/- pp reference baseline."
            ),
            "evidence_reference": (
                f"timeseries.csv row {prior_period} — headline_pce_yoy_pct = "
                f"{_fmt_num(prev_headline, 3)}"
            ),
        })
    if prior_period and prev_core is not None:
        evid.append({
            "observation": (
                f"Prior month {prior_period} core PCE YoY was {prev_core:.2f}%, "
                f"establishing the sticky-core baseline."
            ),
            "evidence_reference": (
                f"timeseries.csv row {prior_period} — core_pce_yoy_pct = "
                f"{_fmt_num(prev_core, 3)}"
            ),
        })
    evid.append({
        "observation": "Fed's 2% PCE target is the institutional reference for vs_fed_target_pp.",
        "evidence_reference": (
            f"gt_source/PCEPI.csv — prior-period context (history through "
            f"{prior_period or period})"
        ),
    })
    return {
        "report_month": period,
        "headline_pce_yoy_pct": round(headline_yoy, 3),
        "core_pce_yoy_pct": round(core_yoy, 3),
        "headline_mom_change_pp": headline_mom_pp,
        "vs_fed_target_pp": vs_target_pp,
        "key_drivers": drivers,
        "outlook_direction_next_period": outlook,
        "report": summary,
        "supporting_evidence": evid,
    }


def render_gt_annotations(gt: dict) -> dict:
    return {
        "headline_pce_yoy_pct": gt["headline_pce_yoy_pct"],
        "core_pce_yoy_pct": gt["core_pce_yoy_pct"],
        "headline_mom_change_pp": gt["headline_mom_change_pp"],
        "vs_fed_target_pp": gt["vs_fed_target_pp"],
        "outlook_direction_next_period": gt["outlook_direction_next_period"],
        "report": gt["report"],
        "supporting_evidence": gt["supporting_evidence"],
    }


def render_gt_evidence_md(period: str, gt: dict, prior_period: str | None,
                          prev_headline: float | None, prev_core: float | None) -> str:
    drivers_list = "\n".join(f"  - `{d}`" for d in gt["key_drivers"])
    return (
        f"# Evidence — BEA PCE Inflation {period}\n"
        f"\n"
        f"## Per-answer-field citations\n"
        f"\n"
        f"- **headline_pce_yoy_pct** -> `{gt['headline_pce_yoy_pct']}`\n"
        f"  - Sourced from timeseries.csv row {period}: headline_pce_yoy_pct = {gt['headline_pce_yoy_pct']}\n"
        f"- **core_pce_yoy_pct** -> `{gt['core_pce_yoy_pct']}`\n"
        f"  - Sourced from timeseries.csv row {period}: core_pce_yoy_pct = {gt['core_pce_yoy_pct']}\n"
        f"- **headline_mom_change_pp** -> `{gt['headline_mom_change_pp']}`\n"
        f"  - Computed as headline_yoy minus prior-month headline_yoy.\n"
        f"- **vs_fed_target_pp** -> `{gt['vs_fed_target_pp']}`\n"
        f"  - Computed as headline_yoy minus 2.0.\n"
        f"- **key_drivers** -> {gt['key_drivers']}\n"
        f"{drivers_list}\n"
        f"  - Heuristic classifier weighs the headline-vs-core gap and the\n"
        f"    monthly trajectory.\n"
        f"- **outlook_direction_next_period** -> `{gt['outlook_direction_next_period']}`\n"
        f"  - Inferred from headline+core month-on-month YoY-pp deltas.\n"
        f"\n"
        f"## CSV-grounded numeric tokens\n"
        f"\n"
        f"- headline_pce_yoy_pct = {gt['headline_pce_yoy_pct']} (timeseries.csv row {period})\n"
        f"- core_pce_yoy_pct = {gt['core_pce_yoy_pct']} (timeseries.csv row {period})\n"
        + (f"- prior-month {prior_period}: headline_pce_yoy_pct = {_fmt_num(prev_headline, 3)} (timeseries.csv row {prior_period})\n" if prior_period and prev_headline is not None else "")
        + (f"- prior-month {prior_period}: core_pce_yoy_pct = {_fmt_num(prev_core, 3)} (timeseries.csv row {prior_period})\n" if prior_period and prev_core is not None else "")
    )


def render_question_md(period: str, template: str) -> str:
    y, m = period.split("-")
    month_names = [None, "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    month_label_long = f"{month_names[int(m)]} {y}"
    return (
        template
        .replace("{{month_label_long}}", month_label_long)
        .replace("{{period_label}}", period)
    )


def main() -> int:
    headline = read_series("PCEPI")
    core = read_series("PCEPILFE")
    if not headline or not core:
        print("ERROR: missing series", file=sys.stderr)
        return 1
    # Build YoY for both
    headline_yoy: dict[str, float] = {}
    core_yoy: dict[str, float] = {}
    for p, v in headline.items():
        ya = shift_month(p, -12)
        y = yoy_pct(v, headline.get(ya))
        if y is not None:
            headline_yoy[p] = round(y, 3)
    for p, v in core.items():
        ya = shift_month(p, -12)
        y = yoy_pct(v, core.get(ya))
        if y is not None:
            core_yoy[p] = round(y, 3)

    INSTANCES.mkdir(parents=True, exist_ok=True)
    schema_path = ENV / "answer_schema.json"
    template_path = ENV / "question_template.md"
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""

    periods_all = sorted(set(headline_yoy.keys()) & set(core_yoy.keys()))

    dist_outlook = Counter()

    for period in QUERY_MONTHS:
        if period not in headline_yoy or period not in core_yoy:
            print(f"WARN: no YoY for {period}", file=sys.stderr)
            continue
        h_y = headline_yoy[period]
        c_y = core_yoy[period]
        prior_period = shift_month(period, -1)
        prev_h = headline_yoy.get(prior_period)
        prev_c = core_yoy.get(prior_period)

        drivers = classify_drivers(period, h_y, c_y, prev_h, prev_c)
        outlook = classify_outlook(period, h_y, prev_h, c_y, prev_c)

        gt = render_ground_truth(period, h_y, c_y, prev_h, prev_c, drivers,
                                 outlook, prior_period)
        ann = render_gt_annotations(gt)
        evidence_md = render_gt_evidence_md(period, gt, prior_period, prev_h, prev_c)
        question_md = render_question_md(period, template)

        inst_dir = INSTANCES / period
        inst_dir.mkdir(parents=True, exist_ok=True)
        render_timeseries_csv(inst_dir, periods_all, headline, core,
                              headline_yoy, core_yoy, period)
        (inst_dir / "ground_truth.json").write_text(
            json.dumps(gt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (inst_dir / "gt_annotations.json").write_text(
            json.dumps(ann, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (inst_dir / "gt_evidence.md").write_text(evidence_md, encoding="utf-8")
        (inst_dir / "question.md").write_text(question_md, encoding="utf-8")
        if schema_path.exists():
            shutil.copy2(schema_path, inst_dir / "answer_schema.json")

        dist_outlook[gt["outlook_direction_next_period"]] += 1

    print("=== V8 distribution ===")
    print(f"outlook_direction_next_period: {dict(dist_outlook)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
