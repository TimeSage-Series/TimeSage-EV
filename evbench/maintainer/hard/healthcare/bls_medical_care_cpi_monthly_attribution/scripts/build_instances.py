"""Build the 23 instance directories for
bls_medical_care_cpi_monthly_attribution.

Reads the cumulative CSV produced by `format.py timeseries`, applies the
oracle from tools/grounding_rules/<id>.py to each row (so that the GT
matches what validate_oracles will derive), and writes per-instance
artifacts: timeseries.csv, ground_truth.json, gt_annotations.json,
gt_evidence.md, question.md, answer_schema.json.

The grounding rule is the single source of truth for the analytical
fields (headline_yoy_direction, leading_subcomponent, key_drivers,
outlook_direction_next_period). Numeric/metadata fields
(headline_yoy_change_pct, report_month) and narrative/list-valued
fields (report, supporting_evidence, event_anomaly_callouts)
are filled in here.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    ENV, INSTANCES, QUERY_MONTHS, SCENARIO_ROOT, TS_SOURCE,
)


MAINTAINER_ROOT = Path(__file__).resolve().parents[4]
GROUNDING_RULE_PATH = MAINTAINER_ROOT / "tools" / "grounding_rules" / (
    "bls_medical_care_cpi_monthly_attribution.py"
)


def load_oracle():
    spec = importlib.util.spec_from_file_location(
        "_bls_medical_oracle", GROUNDING_RULE_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def read_cumulative() -> list[dict]:
    src = TS_SOURCE / "medical_care_cpi_full.csv"
    out: list[dict] = []
    with src.open() as f:
        for row in csv.DictReader(f):
            out.append(row)
    return out


def _fmt(x, n: int) -> str:
    if x is None or x == "":
        return ""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    s = f"{v:.{n}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def render_timeseries_csv(inst_dir: Path, all_rows: list[dict], cur_period: str,
                          fieldnames: list[str]) -> None:
    out = inst_dir / "timeseries.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in all_rows:
            if r["period"] > cur_period:
                break
            w.writerow(r)


def shift_month(period: str, months: int) -> str:
    y, m = period.split("-")
    yi = int(y); mi = int(m)
    mi += months
    while mi <= 0:
        yi -= 1; mi += 12
    while mi > 12:
        yi += 1; mi -= 12
    return f"{yi:04d}-{mi:02d}"


MONTH_NAMES = [None, "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


def render_report(period: str, derived: dict, headline_yoy: float | None,
                         leading_pp: float | None) -> str:
    """1-3 sentence factual coverage summary."""
    direction = derived.get("headline_yoy_direction", "stable")
    leading = derived.get("leading_subcomponent")
    drivers = derived.get("key_drivers") or []
    outlook = derived.get("outlook_direction_next_period", "unclear")
    drivers_str = ", ".join(d.replace("_", " ") for d in drivers)
    leading_str = (leading or "").replace("_", " ")
    if leading and leading_pp is not None:
        lead_clause = (
            f"The leading sub-component this month was {leading_str} on a "
            f"{leading_pp:+.2f} pp MoM acceleration"
        )
    elif leading:
        lead_clause = f"The leading sub-component this month was {leading_str}"
    else:
        lead_clause = "Sub-component leadership was inconclusive this month"

    summary = (
        f"In {period}, headline Medical Care CPI ran at {headline_yoy:.2f}% YoY, "
        f"{direction} versus the prior month. "
        f"{lead_clause}; drivers: {drivers_str}. "
        f"Forward outlook: {outlook}."
    )
    return summary[:799]


def render_supporting_evidence(period: str, all_rows: list[dict],
                               prior_period: str | None,
                               prev_headline_yoy: float | None,
                               prev_leading_yoy: float | None,
                               leading_sub: str | None,
                               prev_headline_yoy_str: str = "",
                               prev_leading_yoy_str: str = "") -> list[dict]:
    evid: list[dict] = []
    if prior_period and prev_headline_yoy is not None:
        evid.append({
            "observation": (
                f"Prior month {prior_period} headline Medical Care CPI YoY was "
                f"{prev_headline_yoy:.2f}%, establishing the baseline against "
                f"which this month's direction label was derived."
            ),
            "evidence_reference": (
                f"timeseries.csv row {prior_period} — medical_care_yoy_pct = "
                f"{prev_headline_yoy_str or _fmt(prev_headline_yoy, 3)}"
            ),
        })
    if prior_period and prev_leading_yoy is not None and leading_sub:
        evid.append({
            "observation": (
                f"Prior month {prior_period} {leading_sub} YoY was "
                f"{prev_leading_yoy:.2f}%, anchoring the MoM YoY-pp "
                f"acceleration this month."
            ),
            "evidence_reference": (
                f"timeseries.csv row {prior_period} — {leading_sub}_yoy_pct = "
                f"{prev_leading_yoy_str or _fmt(prev_leading_yoy, 3)}"
            ),
        })
    if prior_period:
        evid.append({
            "observation": (
                "The prior-period BLS CPI news-release PDF documents the "
                "macro context for medical-care price trends entering the "
                "current report month."
            ),
            "evidence_reference": (
                f"gt_source/{prior_period}.pdf — BLS CPI release covering "
                f"data month {prior_period}"
            ),
        })
    while len(evid) < 2:
        evid.append({
            "observation": (
                "FRED CPIMEDSL is the canonical mirror of BLS Medical Care "
                "CPI used to derive headline YoY and sub-component shares."
            ),
            "evidence_reference": (
                "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIMEDSL "
                "(public time-series archive; mirrors BLS series CPIMEDSL)"
            ),
        })
    return evid


def render_event_anomaly_callouts(leading_sub: str | None, drivers: list[str]) -> list[str]:
    """Map leading_sub + drivers onto the closed D1 vocab."""
    out: list[str] = []
    sub_map = {
        "hospital_services": "hospital_services",
        "professional_services": "physician_services",
        "medical_services": "physician_services",
        "medical_commodities": "prescription_drugs",
    }
    if leading_sub and sub_map.get(leading_sub):
        out.append(sub_map[leading_sub])
    driver_map = {
        "prescription_drug_pricing": "prescription_drugs",
        "drug_shortages": "prescription_drugs",
        "generic_substitution": "prescription_drugs",
        "rx_price_negotiation": "prescription_drugs",
        "medicare_rate_update": "medicare_pricing",
        "physician_fee_schedule": "physician_services",
        "hospital_labor_costs": "hospital_services",
        "hospital_consolidation": "hospital_services",
        "insurance_reset": "health_insurance",
    }
    for d in drivers:
        tok = driver_map.get(d)
        if tok and tok not in out:
            out.append(tok)
        if len(out) >= 3:
            break
    return out[:3]


def render_gt_evidence_md(period: str, gt: dict, prior_period: str | None,
                          prev_headline_yoy: float | None,
                          prev_leading_yoy: float | None,
                          leading_sub: str | None,
                          cur_headline_yoy_str: str,
                          prev_headline_yoy_str: str,
                          prev_leading_yoy_str: str) -> str:
    drivers_list = "\n".join(f"  - `{d}`" for d in gt.get("key_drivers", []))
    out = (
        f"# Evidence — BLS Medical Care CPI {period}\n"
        f"\n"
        f"## Per-answer-field citations\n"
        f"\n"
        f"- **headline_yoy_change_pct** -> `{gt['headline_yoy_change_pct']}`\n"
        f"  - Sourced from timeseries.csv row {period}: medical_care_yoy_pct = "
        f"{cur_headline_yoy_str}\n"
        f"- **headline_yoy_direction** -> `{gt['headline_yoy_direction']}`\n"
        f"  - Classified from the MoM YoY-pp delta of the headline.\n"
        f"- **leading_subcomponent** -> `{gt.get('leading_subcomponent', '')}`\n"
        f"  - Argmax of MoM YoY-pp acceleration across the 4 sub-components.\n"
        f"- **key_drivers** -> {gt.get('key_drivers', [])}\n"
        f"{drivers_list}\n"
        f"  - Heuristic classifier weighs the headline + leading-sub trajectory.\n"
        f"- **outlook_direction_next_period** -> `{gt['outlook_direction_next_period']}`\n"
        f"  - Inferred from the headline MoM YoY-pp delta.\n"
        f"\n"
        f"## CSV-grounded numeric tokens\n"
        f"\n"
        f"- medical_care_yoy_pct = {cur_headline_yoy_str} "
        f"(timeseries.csv row {period})\n"
    )
    if prior_period and prev_headline_yoy_str:
        out += (
            f"- prior-month {prior_period}: medical_care_yoy_pct = "
            f"{prev_headline_yoy_str} (timeseries.csv row {prior_period})\n"
        )
    if prior_period and prev_leading_yoy_str and leading_sub:
        out += (
            f"- prior-month {prior_period}: {leading_sub}_yoy_pct = "
            f"{prev_leading_yoy_str} (timeseries.csv row {prior_period})\n"
        )
    return out


def render_question_md(period: str, template: str) -> str:
    y, m = period.split("-")
    month_label_long = f"{MONTH_NAMES[int(m)]} {y}"
    return (template
            .replace("{{month_label_long}}", month_label_long)
            .replace("{{period_label}}", period))


def main() -> int:
    oracle = load_oracle()
    cumulative = read_cumulative()
    fieldnames = list(cumulative[0].keys())

    by_period: dict[str, dict] = {r["period"]: r for r in cumulative}

    INSTANCES.mkdir(parents=True, exist_ok=True)
    schema_path = ENV / "answer_schema.json"
    template_path = ENV / "question_template.md"
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""

    dist_direction: Counter[str] = Counter()
    dist_leading: Counter[str] = Counter()
    dist_outlook: Counter[str] = Counter()
    n_built = 0
    for period in QUERY_MONTHS:
        row = by_period.get(period)
        if not row or not row.get("medical_care_yoy_pct"):
            print(f"WARN: no row for {period}", file=sys.stderr)
            continue

        # Build history (all rows up to and including this period).
        history = [r for r in cumulative if r["period"] <= period]
        latest = history[-1]

        derived = oracle.derive_gt(latest, history, None)

        period_label = period
        headline_yoy = float(latest["medical_care_yoy_pct"])
        leading_sub = derived.get("leading_subcomponent")
        leading_pp_str = (latest.get(f"{leading_sub}_mom_yoy_delta_pp")
                          if leading_sub else "")
        try:
            leading_pp = float(leading_pp_str) if leading_pp_str else None
        except ValueError:
            leading_pp = None

        prior_period = shift_month(period, -1)
        prior_row = by_period.get(prior_period)
        prev_headline_yoy = None
        prev_leading_yoy = None
        if prior_row:
            try:
                prev_headline_yoy = (float(prior_row["medical_care_yoy_pct"])
                                     if prior_row.get("medical_care_yoy_pct") else None)
            except ValueError:
                pass
            if leading_sub:
                try:
                    pv = prior_row.get(f"{leading_sub}_yoy_pct")
                    prev_leading_yoy = float(pv) if pv else None
                except ValueError:
                    pass

        gt = dict(derived)
        gt["report"] = render_report(
            period, derived, headline_yoy, leading_pp
        )
        gt["supporting_evidence"] = render_supporting_evidence(
            period, history, prior_period, prev_headline_yoy,
            prev_leading_yoy, leading_sub,
            (prior_row or {}).get("medical_care_yoy_pct", ""),
            (prior_row or {}).get(f"{leading_sub}_yoy_pct", "") if leading_sub else ""
        )
        # event_anomaly_callouts intentionally NOT emitted by the oracle (it
        # would need current-period PDF text). We synthesize a derived
        # publisher-emphasis token list from leading_sub + drivers to give
        # the agent a meaningful set_match target — this is a heuristic
        # proxy aligned with the field's intent.
        gt["event_anomaly_callouts"] = render_event_anomaly_callouts(
            leading_sub, derived.get("key_drivers") or []
        )

        # Materialize instance directory
        inst_dir = INSTANCES / period
        inst_dir.mkdir(parents=True, exist_ok=True)
        render_timeseries_csv(inst_dir, cumulative, period, fieldnames)
        (inst_dir / "ground_truth.json").write_text(
            json.dumps(gt, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )
        ann = {k: v for k, v in gt.items() if k not in ("report_month",)}
        (inst_dir / "gt_annotations.json").write_text(
            json.dumps(ann, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )
        cur_headline_yoy_str = latest.get("medical_care_yoy_pct", "")
        prev_headline_yoy_str = (prior_row or {}).get("medical_care_yoy_pct", "")
        prev_leading_yoy_str = (
            (prior_row or {}).get(f"{leading_sub}_yoy_pct", "") if leading_sub else ""
        )
        ev_md = render_gt_evidence_md(period, gt, prior_period,
                                      prev_headline_yoy, prev_leading_yoy,
                                      leading_sub,
                                      cur_headline_yoy_str,
                                      prev_headline_yoy_str,
                                      prev_leading_yoy_str)
        (inst_dir / "gt_evidence.md").write_text(ev_md, encoding="utf-8")
        (inst_dir / "question.md").write_text(
            render_question_md(period, template), encoding="utf-8"
        )
        if schema_path.exists():
            shutil.copy2(schema_path, inst_dir / "answer_schema.json")

        dist_direction[gt["headline_yoy_direction"]] += 1
        if leading_sub:
            dist_leading[leading_sub] += 1
        dist_outlook[gt["outlook_direction_next_period"]] += 1
        n_built += 1

    print(f"=== Built {n_built} instances ===")
    print(f"headline_yoy_direction: {dict(dist_direction)}")
    print(f"leading_subcomponent: {dict(dist_leading)}")
    print(f"outlook_direction_next_period: {dict(dist_outlook)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
