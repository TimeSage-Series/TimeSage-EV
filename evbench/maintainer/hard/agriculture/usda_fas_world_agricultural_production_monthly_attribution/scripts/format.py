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
from _common import (  # noqa: E402
    TS_SOURCE, INSTANCES, SERIES, START_LABEL, END_LABEL, EARLIEST_RAW,
    iter_months, month_label,
)
import json
from _common import (  # noqa: E402
    GT_SOURCE, INSTANCES, ENV, iter_months, long_month_label, month_label,
    prior_month, START_LABEL, END_LABEL,
)
MAINTAINER_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(MAINTAINER_ROOT / "lib"))
from narrative_extract import build_narrative_md_block, load_source_text  # noqa: E402


# --- step: timeseries ----------------------------------------------------


COLUMNS = [
    "as_of_data_month",
    "release_year",
    "release_month",
    "wheat_price_usd_mt",
    "wheat_price_mom_pct",
    "wheat_price_yoy_pct",
    "maize_price_usd_mt",
    "maize_price_mom_pct",
    "maize_price_yoy_pct",
    "soybean_price_usd_mt",
    "soybean_price_mom_pct",
    "soybean_price_yoy_pct",
    "rice_price_usd_mt",
    "rice_price_mom_pct",
    "rice_price_yoy_pct",
    "basket_avg_mom_pct",
    "basket_mom_dispersion_pp",
]

CROPS = [
    ("wheat", "wheat_price_usd_mt"),
    ("maize", "maize_price_usd_mt"),
    ("soybean", "soybean_price_usd_mt"),
    ("rice", "rice_price_usd_mt"),
]


def load_fred(series_id: str) -> dict[str, float]:
    path = TS_SOURCE / f"{series_id}.csv"
    out: dict[str, float] = {}
    with path.open() as fh:
        for r in csv.DictReader(fh):
            d = r.get("observation_date", "")
            if not d:
                continue
            ym = d[:7]
            v = r.get(series_id) or r.get(series_id.upper()) or ""
            if v in ("", "."):
                continue
            try:
                out[ym] = float(v)
            except ValueError:
                continue
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
    if v is None:
        return ""
    if isinstance(v, float):
        # Drop pseudo-precision noise
        return f"{v:.4f}".rstrip("0").rstrip(".") if abs(v) > 0 else "0"
    return str(v)


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    args = ap.parse_args()

    series_by_crop = {label: load_fred(sid) for label, sid in SERIES.items()}
    months = sorted(set().union(*[s.keys() for s in series_by_crop.values()]))
    months = [m for m in months if m >= EARLIEST_RAW]
    print(f"[ok] {len(months)} months in CSV ({months[0]} -> {months[-1]})",
          file=sys.stderr)

    by_month: dict[str, dict] = {}
    for m in months:
        rec = {}
        for crop, col in CROPS:
            rec[col] = series_by_crop[col].get(m)
        if all(rec.get(c) is None for _, c in CROPS):
            continue
        y, mo = (int(x) for x in m.split("-"))
        rec["as_of_data_month"] = m
        rec["release_year"] = y
        rec["release_month"] = mo
        by_month[m] = rec

    sorted_months = sorted(by_month.keys())
    rows: list[dict] = [by_month[m] for m in sorted_months]
    # Compute MoM/YoY per crop and basket aggregates.
    for i in range(len(rows)):
        moms = []
        for crop, col in CROPS:
            mom = mom_pct(rows, i, col)
            yoy = yoy_pct(rows, i, col)
            rows[i][f"{crop}_price_mom_pct"] = mom
            rows[i][f"{crop}_price_yoy_pct"] = yoy
            if mom is not None:
                moms.append(mom)
        if moms:
            avg = sum(moms) / len(moms)
            disp = max(moms) - min(moms)
            rows[i]["basket_avg_mom_pct"] = round(avg, 2)
            rows[i]["basket_mom_dispersion_pp"] = round(disp, 2)
        else:
            rows[i]["basket_avg_mom_pct"] = None
            rows[i]["basket_mom_dispersion_pp"] = None

    INSTANCES.mkdir(parents=True, exist_ok=True)

    # Determine which instance months actually have a GT PDF.
    gt_root = TS_SOURCE.parent / "gt_source"
    available = {p.stem for p in gt_root.glob("*.pdf")}
    print(f"[ok] {len(available)} GT PDF months available", file=sys.stderr)

    n_written = 0
    for d in iter_months(START_LABEL, END_LABEL):
        lbl = month_label(d)
        if lbl not in available:
            print(f"[skip] {lbl}: no GT PDF in gt_source/", file=sys.stderr)
            continue
        # Keep all rows at or before this label.
        keep = [r for r in rows if r["as_of_data_month"] <= lbl]
        if not keep or keep[-1]["as_of_data_month"] != lbl:
            print(f"[skip] {lbl}: FRED has no row for this month", file=sys.stderr)
            continue
        inst = INSTANCES / lbl
        inst.mkdir(parents=True, exist_ok=True)
        out = inst / "timeseries.csv"
        with out.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(COLUMNS)
            for r in keep:
                w.writerow([_fmt(r.get(c)) for c in COLUMNS])
        n_written += 1
        print(f"[csv] {lbl}: {len(keep)} rows", file=sys.stderr)
    print(f"wrote {n_written} instance CSVs", file=sys.stderr)
    return 0


# --- step: gt ------------------------------------------------------------
CROPS__gt = ["wheat", "maize", "soybean", "rice"]
QUESTION_TEMPLATE = (ENV / "question_template.md").read_text()


def _to_float(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def basket_direction(yoy: float | None) -> str:
    if yoy is None:
        return "flat"
    if yoy > 1.5:
        return "up"
    if yoy < -1.5:
        return "down"
    return "flat"


def basket_avg_yoy(latest: dict) -> float | None:
    vals = []
    for c in CROPS__gt:
        v = _to_float(latest.get(f"{c}_price_yoy_pct"))
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def leading_commodity(latest: dict) -> str | None:
    """Argmax |YoY%| over the four crops; alphabetical tie-break."""
    scores: dict[str, float] = {}
    for c in CROPS__gt:
        v = _to_float(latest.get(f"{c}_price_yoy_pct"))
        if v is not None:
            scores[c] = abs(v)
    if not scores:
        return None
    # Sort by (-|YoY%|, alphabetical name) — alphabetical tie-break.
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


# Heuristic driver mapping by leading crop + season window.
DRIVER_BY_CROP = {
    "wheat":   ["weather_impact", "yield_change", "planted_area_shift",
                "geopolitical_supply_risk", "export_policy"],
    "maize":   ["weather_impact", "yield_change", "harvest_progress",
                "input_cost", "import_demand_shift"],
    "soybean": ["harvest_progress", "yield_change", "planted_area_shift",
                "weather_impact", "import_demand_shift"],
    "rice":    ["weather_impact", "yield_change", "export_policy",
                "import_demand_shift", "seasonality"],
}


def pick_drivers(leading: str | None, release_month: int,
                 history: list[dict]) -> list[str]:
    if not leading:
        return ["seasonality", "other"]
    candidates = list(DRIVER_BY_CROP.get(leading, ["other"]))
    # Seasonal booster: NH harvest months Jun-Sep -> push harvest_progress.
    if release_month in (6, 7, 8, 9) and "harvest_progress" not in candidates:
        candidates.insert(1, "harvest_progress")
    # SH harvest months Mar-May (soybeans) -> seasonality.
    if release_month in (3, 4, 5) and "seasonality" not in candidates:
        candidates.insert(2, "seasonality")
    # Volatility booster: trailing-3 |basket_avg_mom_pct| avg > 4 pp -> add
    # geopolitical_supply_risk.
    if len(history) >= 4:
        trail = [_to_float(r.get("basket_avg_mom_pct"))
                 for r in history[-4:-1]]
        trail = [t for t in trail if t is not None]
        if trail:
            avg_abs = sum(abs(t) for t in trail) / len(trail)
            if avg_abs > 4.0 and "geopolitical_supply_risk" not in candidates:
                candidates.append("geopolitical_supply_risk")
    return candidates[:3] if len(candidates) >= 2 else candidates + ["other"]


def outlook_next(history: list[dict]) -> str:
    """Trailing-3-row basket-YoY% trajectory.

    - rising:   last 2 basket-YoY rows ascending AND latest >= +3 pp
    - easing:   last 2 basket-YoY rows descending AND latest <= -3 pp
    - sideways: trailing 3 rows oscillate (sign changes) with |delta| < 2 pp
    - unclear:  otherwise
    """
    trail = []
    for r in history[-3:]:
        # Use the just-computed basket_avg_yoy_pct = mean of per-crop yoys
        per = [_to_float(r.get(f"{c}_price_yoy_pct")) for c in CROPS__gt]
        per = [p for p in per if p is not None]
        if per:
            trail.append(sum(per) / len(per))
    if len(trail) < 2:
        return "unclear"
    last = trail[-1]
    second = trail[-2]
    if last > second + 0.5 and last >= 3.0:
        return "rising"
    if last < second - 0.5 and last <= -3.0:
        return "easing"
    if len(trail) >= 3:
        deltas = [trail[i+1] - trail[i] for i in range(len(trail) - 1)]
        if any(d > 0 for d in deltas) and any(d < 0 for d in deltas):
            if max(abs(d) for d in deltas) < 2.0:
                return "sideways"
    return "unclear"


def build_supporting_evidence(period: str, latest: dict, history: list[dict],
                              leading: str | None, drivers: list[str],
                              avail_pdfs: set[str]) -> list[dict]:
    items: list[dict] = []
    avg_yoy = basket_avg_yoy(latest)
    if avg_yoy is not None:
        items.append({
            "observation": (
                f"4-crop basket-average YoY moved {avg_yoy:+.2f}% in {period}, "
                f"derived from the four per-crop YoY columns on the latest CSV row."
            ),
            "evidence_reference": (
                f"timeseries.csv row {period} — wheat_price_yoy_pct, "
                f"maize_price_yoy_pct, soybean_price_yoy_pct, rice_price_yoy_pct "
                f"(arithmetic mean = {avg_yoy:+.2f})"
            ),
        })
    if leading:
        ldr_yoy = _to_float(latest.get(f"{leading}_price_yoy_pct"))
        ldr_px = _to_float(latest.get(f"{leading}_price_usd_mt"))
        if ldr_yoy is not None and ldr_px is not None:
            items.append({
                "observation": (
                    f"{leading.capitalize()} priced {ldr_px:.1f} USD/MT and moved "
                    f"{ldr_yoy:+.2f}% YoY in {period}, the largest absolute YoY "
                    f"move among the 4 staples."
                ),
                "evidence_reference": (
                    f"timeseries.csv row {period} — "
                    f"{leading}_price_yoy_pct = {ldr_yoy:+.2f}, "
                    f"{leading}_price_usd_mt = {ldr_px:.1f}"
                ),
            })
    # Prior-period WAP PDF citation (only if available in our gt_source).
    p = prior_month(period)
    while p >= "2024-01" and p not in avail_pdfs:
        p = prior_month(p)
    if p in avail_pdfs:
        items.append({
            "observation": (
                f"Prior-period WAP bulletin {p} narrates the country-by-country "
                f"setting that informs this month's driver attribution; trajectory "
                f"context (basket dispersion + leading-crop persistence) is anchored "
                f"on that prior commentary."
            ),
            "evidence_reference": (
                f"gt_source/{p}.pdf — prior-period USDA FAS World Agricultural "
                f"Production bulletin (country production commentary section)"
            ),
        })
    # Driver-supporting evidence: cite a CSV cell range.
    if drivers and leading:
        items.append({
            "observation": (
                f"Driver inference (chosen: {', '.join(drivers)}) leans on the "
                f"trailing FRED-mirrored {leading} price trajectory and the "
                f"canonical crop-to-driver vocabulary documented in the session "
                f"brief."
            ),
            "evidence_reference": (
                f"timeseries.csv columns — {leading}_price_usd_mt, "
                f"{leading}_price_mom_pct, {leading}_price_yoy_pct "
                f"(trailing 3 rows ending {period})"
            ),
        })
    return items


def report_text(period: str, direction: str, avg_yoy: float | None,
                       leading: str | None, drivers: list[str],
                       outlook: str) -> str:
    parts: list[str] = []
    if avg_yoy is not None:
        parts.append(
            f"In {period}, the WAP 4-crop basket moved {direction} by "
            f"{avg_yoy:+.2f}% YoY."
        )
    else:
        parts.append(f"In {period}, the WAP 4-crop basket-YoY direction was {direction}.")
    if leading:
        parts.append(f"The move was led by {leading} on the largest absolute YoY swing.")
    if drivers:
        parts.append(f"Key drivers in scope: {', '.join(drivers)}.")
    parts.append(f"Forward inference for next release: {outlook}.")
    return " ".join(parts)[:800]


def event_anomaly_callouts(leading: str | None, drivers: list[str]) -> list[str]:
    """Map deterministic driver/commodity signals onto the closed D1 vocabulary."""
    out: list[str] = []
    driver_map = {
        "weather_impact": "weather_shock",
        "yield_change": "yield_revision",
        "planted_area_shift": "area_change",
        "geopolitical_supply_risk": "geopolitical_supply",
        "export_policy": "export_restriction",
    }
    for d in drivers:
        tok = driver_map.get(d)
        if tok and tok not in out:
            out.append(tok)
        if len(out) >= 3:
            return out
    if leading in {"wheat", "maize", "soybean", "rice"} and "yield_revision" not in out:
        out.append("yield_revision")
    return out[:3]


def emit_gt_evidence_md(period: str, gt: dict, latest: dict,
                       history: list[dict]) -> str:
    leading = gt.get("leading_commodity_contributor")
    avg_yoy = gt.get("basket_avg_yoy_pct")
    lines: list[str] = []
    lines.append(f"# Evidence — USDA FAS WAP {period}")
    lines.append("")
    lines.append("## Per-answer-field citations")
    lines.append("")
    lines.append(f"- **basket_yoy_direction** -> `{gt['basket_yoy_direction']}`")
    lines.append(f"  - Computed basket_avg_yoy_pct = {avg_yoy}; +-1.5 pp deadband applied.")
    lines.append(f"- **basket_avg_yoy_pct** -> `{avg_yoy}`")
    lines.append("  - Arithmetic mean of {wheat,maize,soybean,rice}_price_yoy_pct on the latest CSV row.")
    if leading:
        ldr_yoy = _to_float(latest.get(f"{leading}_price_yoy_pct"))
        ldr_px = _to_float(latest.get(f"{leading}_price_usd_mt"))
        lines.append(f"- **leading_commodity_contributor** -> `{leading}`")
        lines.append(f"  - timeseries.csv row {period} `{leading}_price_yoy_pct` = {ldr_yoy}; "
                     f"`{leading}_price_usd_mt` = {ldr_px}. Largest |YoY%| among 4 crops.")
    lines.append(f"- **key_drivers** -> `{gt['key_drivers']}`")
    lines.append("  - Heuristic: leading crop -> driver vocab map + seasonal booster "
                 "+ volatility booster (>4 pp trailing-3 |basket-MoM| avg).")
    lines.append(f"- **outlook_direction_next_period** -> `{gt['outlook_direction_next_period']}`")
    lines.append("  - Trailing-3-row basket-YoY trajectory rule. Forward inference, "
                 "not a prediction of an unpublished bulletin.")
    lines.append("- **report** -> templated 1-3 sentence factual summary.")
    lines.append("- **supporting_evidence** -> at least 2 items grounded in CSV cells "
                 "and (when available) a prior-month WAP PDF.")
    lines.append("")
    lines.append("## Trailing trajectory (last 4 rows)")
    lines.append("")
    lines.append("| period | wheat_yoy% | maize_yoy% | soybean_yoy% | rice_yoy% | basket_avg_mom% |")
    lines.append("|--------|-----------|-----------|--------------|-----------|-----------------|")
    for r in history[-4:]:
        def _f(c):
            v = _to_float(r.get(c))
            return f"{v:+.2f}" if v is not None else ""
        lines.append(
            f"| {r.get('as_of_data_month','')} | {_f('wheat_price_yoy_pct')} | "
            f"{_f('maize_price_yoy_pct')} | {_f('soybean_price_yoy_pct')} | "
            f"{_f('rice_price_yoy_pct')} | {_f('basket_avg_mom_pct')} |"
        )
    return "\n".join(lines) + "\n"


def render_question(period: str) -> str:
    return (QUESTION_TEMPLATE
            .replace("{{period_label}}", period)
            .replace("{{month_label_long}}", long_month_label(period)))


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    args = ap.parse_args()

    avail_pdfs = {p.stem for p in GT_SOURCE.glob("*.pdf")}
    print(f"[ok] {len(avail_pdfs)} prior PDFs available", file=sys.stderr)

    n_written = 0
    for d in iter_months(START_LABEL, END_LABEL):
        label = month_label(d)
        inst = INSTANCES / label
        ts_path = inst / "timeseries.csv"
        if not ts_path.exists():
            print(f"[skip] {label}: no timeseries.csv", file=sys.stderr)
            continue
        history = read_csv(ts_path)
        if not history:
            print(f"[skip] {label}: empty timeseries.csv", file=sys.stderr)
            continue
        latest = history[-1]
        if latest.get("as_of_data_month") != label:
            print(f"[skip] {label}: last CSV row label mismatch "
                  f"({latest.get('as_of_data_month')})", file=sys.stderr)
            continue
        avg_yoy = basket_avg_yoy(latest)
        direction = basket_direction(avg_yoy)
        leading = leading_commodity(latest)
        release_month = int(label.split("-")[1])
        drivers = pick_drivers(leading, release_month, history)
        outlook = outlook_next(history)
        # Only cite prior PDFs strictly before this label.
        prior_pdfs = {x for x in avail_pdfs if x < label}
        evidence = build_supporting_evidence(label, latest, history, leading,
                                             drivers, prior_pdfs)
        gt = {
            "report_month": label,
            "basket_yoy_direction": direction,
            "basket_avg_yoy_pct": avg_yoy if avg_yoy is not None else 0.0,
            "leading_commodity_contributor": leading or "wheat",
            "key_drivers": drivers,
            "outlook_direction_next_period": outlook,
            "report": report_text(label, direction, avg_yoy, leading,
                                                drivers, outlook),
            "supporting_evidence": evidence,
            "event_anomaly_callouts": event_anomaly_callouts(leading, drivers),
        }
        (inst / "ground_truth.json").write_text(
            json.dumps(gt, indent=2), encoding="utf-8")
        ev_text = emit_gt_evidence_md(label, gt, latest, history)
        src_text, src_pages = load_source_text(GT_SOURCE / f"{label}.pdf")
        if src_text:
            ev_text = ev_text.rstrip() + "\n\n" + build_narrative_md_block(
                f"gt_source/{label}.pdf", src_text, pages=src_pages,
            )
        (inst / "gt_evidence.md").write_text(ev_text, encoding="utf-8")
        (inst / "question.md").write_text(render_question(label), encoding="utf-8")
        (inst / "visible_reports.json").write_text(json.dumps({
            "scenario_id": "usda_fas_world_agricultural_production_monthly_attribution",
            "report_month": label,
            "accessible_artifacts": sorted(prior_pdfs),
        }, indent=2), encoding="utf-8")
        n_written += 1
        print(f"[ok]   {label}: dir={direction} yoy={avg_yoy} leader={leading} "
              f"drivers={drivers} outlook={outlook}", file=sys.stderr)
    print(f"wrote {n_written} ground_truth.json instances", file=sys.stderr)
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
