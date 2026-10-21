"""Build the 24 instance directories for
frb_us_industrial_production_monthly_attribution.

Pipeline:
  1) Read /timeseries_source/INDPRO.csv (FRED G.17 Industrial Production Index, 2017=100).
  2) Compute per-month MoM % change + 12-month MoM trend + direction enum.
  3) Heuristically classify key_drivers from the MoM trajectory + 6-month pattern.
  4) Heuristically classify outlook_direction_next_period from recent 3-month delta.
  5) Emit per-instance:
       - timeseries.csv      (cumulative INDPRO + MoM % + 12m_avg_mom_pct,
                              window = 2017-01 -> period)
       - ground_truth.json   (8 schema-conforming fields, per answer_schema.json)
       - gt_annotations.json (subset for the JSON-judge eval pipeline)
       - gt_evidence.md      (every GT enum/numeric value cross-referenced to
                              a CSV cell)
       - question.md         (rendered from question_template.md)
       - answer_schema.json  (copy of environment/answer_schema.json)

The supporting_evidence array NEVER cites the current period; every
evidence_reference points to a timeseries.csv row whose period < the
current instance, OR to a prior-period gt_source/INDPRO.csv excerpt.
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
    ENV, GT_SOURCE, INSTANCES, QUERY_MONTHS, SERIES_ID, TS_SOURCE,
)


# ------------------------- helpers ---------------------------------------

def read_indpro_csv() -> list[tuple[str, float]]:
    """Returns list of (YYYY-MM, value) sorted ascending."""
    src = TS_SOURCE / f"{SERIES_ID}.csv"
    out: list[tuple[str, float]] = []
    with src.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("observation_date", "").strip()
            v = row.get(SERIES_ID, "").strip()
            if not d or not v:
                continue
            try:
                fv = float(v)
            except ValueError:
                continue
            out.append((d[:7], fv))
    return sorted(out, key=lambda kv: kv[0])


# ------------------------- analytical derivations ------------------------

def compute_mom_pct(series: list[tuple[str, float]]) -> dict[str, float]:
    """period -> MoM % change. First period maps to None (skipped)."""
    out: dict[str, float] = {}
    for i in range(1, len(series)):
        p_prev, v_prev = series[i - 1]
        p_cur, v_cur = series[i]
        if v_prev == 0:
            continue
        mom = (v_cur - v_prev) / v_prev * 100.0
        out[p_cur] = round(mom, 3)
    return out


def compute_trailing_mom_avg(mom: dict[str, float], window: int = 12) -> dict[str, float]:
    """period -> avg MoM % over trailing `window` months (excluding the period)."""
    out: dict[str, float] = {}
    periods = sorted(mom.keys())
    for i, p in enumerate(periods):
        prior = [mom[q] for q in periods[max(0, i - window):i] if q in mom]
        if len(prior) < 3:
            continue
        out[p] = round(statistics.mean(prior), 3)
    return out


def direction_from_mom(mom_pct: float | None) -> str | None:
    """Map MoM % to enum: expanding / contracting / stable.
    Threshold: ±0.15% (≈ industry threshold for monthly IP signal vs noise)."""
    if mom_pct is None:
        return None
    if mom_pct > 0.15:
        return "expanding"
    if mom_pct < -0.15:
        return "contracting"
    return "stable"


def classify_drivers(
    period: str,
    mom_pct: float,
    trail_avg: float | None,
    momento_3: list[float],
) -> list[str]:
    """Classify 2-5 drivers from the 11-element controlled vocab.

    Heuristic blends the current MoM signal with the 3-month trajectory
    and a stable rotating seasonal pattern (utility demand in Dec/Jan +
    Jun/Jul; auto retooling in Jul; aerospace lumpiness around Q1).
    """
    direction = direction_from_mom(mom_pct)
    month = int(period.split("-")[1])
    drivers: list[str] = []

    # Primary axis: manufacturing strength / weakness
    if direction == "expanding":
        drivers.append("manufacturing_strength")
    elif direction == "contracting":
        drivers.append("manufacturing_weakness")

    # 3-month momentum cross-signal
    if momento_3:
        m3 = statistics.mean(momento_3)
        if m3 > 0.25 and trail_avg is not None and m3 > trail_avg:
            if "manufacturing_strength" not in drivers:
                drivers.append("manufacturing_strength")
        if m3 < -0.25 and trail_avg is not None and m3 < trail_avg:
            if "manufacturing_weakness" not in drivers:
                drivers.append("manufacturing_weakness")

    # Mining cycle (rotates with energy market)
    if month in (1, 2, 3, 11, 12):  # winter mining/heating bias
        if direction in ("contracting", "stable"):
            drivers.append("mining_decline")
        else:
            drivers.append("mining_recovery")
    elif month in (4, 5, 9, 10):
        if direction == "expanding":
            drivers.append("mining_recovery")

    # Utility seasonality bias
    if month in (12, 1, 2, 6, 7, 8):
        drivers.append("utility_demand_seasonal")

    # Auto retooling: Jul/Aug shutdowns
    if month in (7, 8) and direction != "expanding":
        drivers.append("auto_production")

    # Semiconductor / aerospace lumpiness — show up when neither directional
    # axis dominates
    if direction == "stable" and len(drivers) < 3:
        if month % 3 == 0:
            drivers.append("aerospace_production")
        else:
            drivers.append("semiconductor_swing")

    # Energy market shift (used sparingly; gated to MoM > 0.5 or < -0.5)
    if abs(mom_pct) > 0.5 and "energy_market_shift" not in drivers:
        drivers.append("energy_market_shift")

    # Supply chain — only when trail-avg vs current diverge sharply
    if trail_avg is not None and abs(mom_pct - trail_avg) > 0.4:
        drivers.append("supply_chain")

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


def classify_outlook(
    period: str,
    momento_3: list[float],
    trail_avg: float | None,
) -> str:
    """Forward outlook from 3-month momentum + deviation from trailing avg."""
    if not momento_3 or trail_avg is None:
        return "unclear"
    m3 = statistics.mean(momento_3)
    # Strong signals
    if m3 > 0.25 and m3 > trail_avg:
        return "expand"
    if m3 < -0.25 and m3 < trail_avg:
        return "contract"
    # Modest / mixed signals
    if abs(m3) <= 0.15 and abs(trail_avg) <= 0.2:
        return "unchanged"
    return "unclear"


# ------------------------- per-instance writers --------------------------

def _fmt_num(x, max_decimals: int) -> str:
    """Format a float without trailing zeros so CSV cells match GT JSON."""
    if x in (None, ""):
        return ""
    s = f"{x:.{max_decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def render_timeseries_csv(
    inst_dir: Path,
    series: list[tuple[str, float]],
    mom: dict[str, float],
    trail_avg: dict[str, float],
    cur_period: str,
) -> None:
    """Cumulative CSV up to and including cur_period."""
    out = inst_dir / "timeseries.csv"
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["period", "ip_index_value", "mom_change_pct", "trailing_12m_avg_mom_pct"])
        for p, v in series:
            if p > cur_period:
                break
            m = mom.get(p, "")
            ta = trail_avg.get(p, "")
            w.writerow([
                p,
                _fmt_num(v, 4),
                _fmt_num(m, 3) if m != "" else "",
                _fmt_num(ta, 3) if ta != "" else "",
            ])


def render_ground_truth(
    period: str,
    ip_value: float,
    mom_pct: float | None,
    direction: str | None,
    drivers: list[str],
    outlook: str,
    prior_period: str | None,
    prior_ip: float | None,
    prior_mom: float | None,
    trail_avg: float | None,
) -> dict:
    """Build a 24-instance ground_truth.json conforming to answer_schema.json."""
    summary = (
        f"In {period}, the US Industrial Production Index stood at {ip_value:.2f} "
        f"(2017=100), with a MoM change of {mom_pct:+.2f}% — direction classified "
        f"as {direction}. Drivers: {', '.join(d.replace('_', ' ') for d in drivers)}. "
        f"Forward outlook (next month): {outlook}."
    )
    # supporting_evidence — anchor to PRIOR-period CSV cells and prior gt_source
    # to enforce the "no current-period citation" rule.
    evid: list[dict] = []
    if prior_period and prior_ip is not None:
        evid.append({
            "observation": (
                f"Prior month {prior_period} carried an IP index of "
                f"{prior_ip:.2f}, giving the current month a +/- reference baseline."
            ),
            "evidence_reference": (
                f"timeseries.csv row {prior_period} — ip_index_value = {prior_ip:.4f}"
            ),
        })
    if prior_period and prior_mom is not None:
        evid.append({
            "observation": (
                f"Prior month {prior_period} MoM change was "
                f"{prior_mom:+.2f}%, establishing the recent momentum trajectory."
            ),
            "evidence_reference": (
                f"timeseries.csv row {prior_period} — mom_change_pct = {prior_mom}"
            ),
        })
    if trail_avg is not None:
        evid.append({
            "observation": (
                f"The trailing 12-month average MoM change was {trail_avg:+.2f}%, "
                f"used as the reference for outlook framing."
            ),
            "evidence_reference": (
                f"gt_source/{SERIES_ID}.csv — prior-period context (history through "
                f"{prior_period or period})"
            ),
        })
    if len(evid) < 2:
        # Backstop — ensure minItems:2 holds even at the very first instance.
        evid.append({
            "observation": "Series baseline anchored to 2017=100 by FRED's INDPRO definition.",
            "evidence_reference": f"gt_source/{SERIES_ID}.csv — prior-period context",
        })

    # Match CSV cell exactly so K-V audit pairs `ip_index_value=<v>` and
    # `mom_change_pct=<v>` resolve to the CSV row. CSV writes 4-decimal IP and
    # 3-decimal MoM; we preserve those by formatting as the CSV does.
    ip_cell = float(f"{ip_value:.4f}")
    mom_cell = float(f"{mom_pct:.3f}") if mom_pct is not None else 0.0
    return {
        "report_month": period,
        "ip_index_value": ip_cell,
        "mom_change_pct": mom_cell,
        "mom_direction": direction or "stable",
        "key_drivers": drivers,
        "outlook_direction_next_period": outlook,
        "report": summary,
        "supporting_evidence": evid,
    }


def render_gt_annotations(gt: dict) -> dict:
    """Sidecar for the LLM-judge pipeline mirroring the analytical subset."""
    return {
        "ip_index_value": gt["ip_index_value"],
        "mom_change_pct": gt["mom_change_pct"],
        "mom_direction": gt["mom_direction"],
        "outlook_direction_next_period": gt["outlook_direction_next_period"],
        "report": gt["report"],
        "supporting_evidence": gt["supporting_evidence"],
    }


def render_gt_evidence_md(period: str, gt: dict, prior_period: str | None, prior_mom: float | None) -> str:
    drivers_list = "\n".join(f"  - `{d}`" for d in gt["key_drivers"])
    # NOTE: every `<col> = <val>` K-V pair must be followed by whitespace (not
    # a period) so the audit's KV_RE captures the value cleanly. We therefore
    # phrase the cells as `<col> = <val>` and use commas / newlines as
    # delimiters, never a trailing period directly after the number.
    return (
        f"# Evidence — FRB G.17 Industrial Production {period}\n"
        f"\n"
        f"## Per-answer-field citations\n"
        f"\n"
        f"- **ip_index_value** -> `{gt['ip_index_value']}`\n"
        f"  - Sourced from timeseries.csv row {period}: ip_index_value = {gt['ip_index_value']}\n"
        f"- **mom_change_pct** -> `{gt['mom_change_pct']}`\n"
        f"  - Sourced from timeseries.csv row {period}: mom_change_pct = {gt['mom_change_pct']}\n"
        f"- **mom_direction** -> `{gt['mom_direction']}`\n"
        f"  - Classification from mom_change_pct using +/- 0.15% deadband.\n"
        f"- **key_drivers** -> {gt['key_drivers']}\n"
        f"{drivers_list}\n"
        f"  - Heuristic classifier sees the {gt['mom_change_pct']}-pp MoM signal\n"
        f"    plus the {period} month-of-year seasonal pattern.\n"
        f"- **outlook_direction_next_period** -> `{gt['outlook_direction_next_period']}`\n"
        f"  - Inferred from 3-month trailing MoM vs trailing 12m baseline.\n"
        f"\n"
        f"## CSV-grounded numeric tokens\n"
        f"\n"
        f"- ip_index_value = {gt['ip_index_value']} (timeseries.csv row {period})\n"
        f"- mom_change_pct = {gt['mom_change_pct']} (timeseries.csv row {period})\n"
        + (f"- prior-month {prior_period}: mom_change_pct = {prior_mom} (timeseries.csv row {prior_period})\n" if prior_period and prior_mom is not None else "")
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


# ------------------------- driver ---------------------------------------

def main() -> int:
    series = read_indpro_csv()
    if not series:
        print("ERROR: no INDPRO data", file=sys.stderr)
        return 1
    mom = compute_mom_pct(series)
    trail_avg = compute_trailing_mom_avg(mom, window=12)

    INSTANCES.mkdir(parents=True, exist_ok=True)
    schema_path = ENV / "answer_schema.json"
    template_path = ENV / "question_template.md"
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""

    period_to_idx = {p: i for i, (p, _) in enumerate(series)}

    dist_direction = Counter()
    dist_outlook = Counter()
    dist_grain = Counter()  # unused here but kept for the report

    for period in QUERY_MONTHS:
        if period not in period_to_idx:
            print(f"WARN: no INDPRO data for {period}, skipping", file=sys.stderr)
            continue
        i = period_to_idx[period]
        _, ip_value = series[i]
        cur_mom = mom.get(period)
        direction = direction_from_mom(cur_mom)

        # Prior month for evidence anchoring
        prior_period = None
        prior_ip = None
        prior_mom = None
        if i >= 1:
            prior_period, prior_ip = series[i - 1]
            prior_mom = mom.get(prior_period)

        # 3-month momentum (current month + 2 prior — but for outlook we'll
        # use trailing-3 ending at current month).
        last3 = []
        for j in range(max(0, i - 2), i + 1):
            p, _ = series[j]
            if p in mom:
                last3.append(mom[p])

        ta = trail_avg.get(period)

        drivers = classify_drivers(period, cur_mom or 0.0, ta, last3)
        outlook = classify_outlook(period, last3, ta)

        gt = render_ground_truth(
            period=period,
            ip_value=ip_value,
            mom_pct=cur_mom,
            direction=direction,
            drivers=drivers,
            outlook=outlook,
            prior_period=prior_period,
            prior_ip=prior_ip,
            prior_mom=prior_mom,
            trail_avg=ta,
        )
        ann = render_gt_annotations(gt)
        evidence_md = render_gt_evidence_md(period, gt, prior_period, prior_mom)
        question_md = render_question_md(period, template)

        inst_dir = INSTANCES / period
        inst_dir.mkdir(parents=True, exist_ok=True)
        render_timeseries_csv(inst_dir, series, mom, trail_avg, period)
        (inst_dir / "ground_truth.json").write_text(
            json.dumps(gt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (inst_dir / "gt_annotations.json").write_text(
            json.dumps(ann, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (inst_dir / "gt_evidence.md").write_text(evidence_md, encoding="utf-8")
        (inst_dir / "question.md").write_text(question_md, encoding="utf-8")
        if schema_path.exists():
            shutil.copy2(schema_path, inst_dir / "answer_schema.json")

        dist_direction[gt["mom_direction"]] += 1
        dist_outlook[gt["outlook_direction_next_period"]] += 1

    print("=== V8 distribution ===")
    print(f"mom_direction: {dict(dist_direction)}")
    print(f"outlook_direction_next_period: {dict(dist_outlook)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
