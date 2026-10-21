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
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import NETWORKS, TS_SOURCE, join_weekly
import json
import shutil
from collections import Counter
from _common import (
    ENV,
    INSTANCES,
    NETWORK_TO_KEY,
    NETWORKS,
    PATHOGEN_LABELS,
    PATHOGEN_TIE_ORDER,
    TS_SOURCE,
    join_weekly,
    target_weeks,
)


# --- step: timeseries ----------------------------------------------------


COLUMNS = [
    "week_ending",
    "mmwr_year",
    "mmwr_week",
    "covid_rate_per_100k",
    "flu_rate_per_100k",
    "rsv_rate_per_100k",
    "combined_rate_per_100k",
    "covid_share_pct",
    "flu_share_pct",
    "rsv_share_pct",
    "combined_wow_delta",
    "combined_4w_delta",
]


def _mmwr(date_str: str) -> tuple[int, int]:
    """Compute MMWR (epi) year and week for a Saturday-ending date.

    MMWR weeks: week 1 is the week containing Jan 4 (or any Sat for which 4 of
    the 7 days are in that calendar year). For simplicity here we use the
    ISO/MMWR-compatible rule: find week's Wednesday and use its year, with
    week-of-year via that Wednesday minus first Wednesday of the year.
    """
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    # week_ending_date is a Saturday in CDC data; Wednesday is d - 3 days.
    wed = d - timedelta(days=3)
    year = wed.year
    # find first Wednesday of that year
    jan1 = wed.replace(month=1, day=1)
    # offset to first Wednesday: weekday() -> Mon=0..Sun=6; Wednesday=2
    off = (2 - jan1.weekday()) % 7
    first_wed = jan1 + timedelta(days=off)
    if wed < first_wed:
        # prior year's last week
        year -= 1
        jan1_prev = jan1.replace(year=year)
        off_p = (2 - jan1_prev.weekday()) % 7
        first_wed = jan1_prev + timedelta(days=off_p)
    week_no = ((wed - first_wed).days // 7) + 1
    return year, week_no


def build_full_history(joined):
    """For every week with all three networks, compute the wide row with
    deltas. Returns a sorted list of dict rows."""
    weeks = sorted(w for w, d in joined.items() if all(k in d for k in NETWORKS))
    by_idx: dict[int, dict] = {}
    for i, w in enumerate(weeks):
        c = joined[w]["COVID-NET"]
        fl = joined[w]["FluSurv-NET"]
        r = joined[w]["RSV-NET"]
        comb = c + fl + r
        if comb > 0:
            covid_pct = 100.0 * c / comb
            flu_pct = 100.0 * fl / comb
            rsv_pct = 100.0 * r / comb
        else:
            covid_pct = flu_pct = rsv_pct = 0.0
        y, wk = _mmwr(w)
        by_idx[i] = {
            "week_ending": w,
            "mmwr_year": y,
            "mmwr_week": wk,
            "covid_rate_per_100k": round(c, 2),
            "flu_rate_per_100k": round(fl, 2),
            "rsv_rate_per_100k": round(r, 2),
            "combined_rate_per_100k": round(comb, 2),
            "covid_share_pct": round(covid_pct, 1),
            "flu_share_pct": round(flu_pct, 1),
            "rsv_share_pct": round(rsv_pct, 1),
        }

    # Deltas — index-based on the joined-week sequence (so a Sep .. Oct gap
    # across off-season still uses adjacent-in-data weeks, which is faithful
    # to how a public-health analyst would read the series).
    for i in range(len(weeks)):
        prev = by_idx.get(i - 1)
        wow = (by_idx[i]["combined_rate_per_100k"] - prev["combined_rate_per_100k"]) if prev else None
        prev4 = by_idx.get(i - 4)
        d4 = (by_idx[i]["combined_rate_per_100k"] - prev4["combined_rate_per_100k"]) if prev4 else None
        by_idx[i]["combined_wow_delta"] = round(wow, 2) if wow is not None else None
        by_idx[i]["combined_4w_delta"] = round(d4, 2) if d4 is not None else None

    return [by_idx[i] for i in range(len(weeks))]


def write_csv_for_period(rows: list[dict], out_path: Path, current_week: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for r in rows:
            if r["week_ending"] > current_week:
                break
            row = [
                r["week_ending"],
                r["mmwr_year"],
                r["mmwr_week"],
                r["covid_rate_per_100k"],
                r["flu_rate_per_100k"],
                r["rsv_rate_per_100k"],
                r["combined_rate_per_100k"],
                r["covid_share_pct"],
                r["flu_share_pct"],
                r["rsv_share_pct"],
                r["combined_wow_delta"] if r["combined_wow_delta"] is not None else "",
                r["combined_4w_delta"] if r["combined_4w_delta"] is not None else "",
            ]
            w.writerow(row)


def _step_timeseries() -> int:
    raw_path = TS_SOURCE / "respnet_raw.csv"
    rows = list(csv.DictReader(raw_path.open()))
    joined = join_weekly(rows)
    full = build_full_history(joined)
    # Smoke check: emit a single full-history snapshot to timeseries_source/.
    out_path = TS_SOURCE / "respnet_full_history.csv"
    write_csv_for_period(full, out_path, full[-1]["week_ending"])
    print(f"Wrote {out_path} ({len(full)} rows)")
    return 0


# --- step: gt ------------------------------------------------------------
# ------------------------------- classifiers ----------------------------

def classify_season_phase(combined: float, delta_4w: float | None,
                          wow: float | None) -> str:
    if combined < 1.5:
        return "off_season"
    if combined >= 5.0:
        return "peak_active"
    if delta_4w is not None and delta_4w > 0.3:
        return "pre_peak_rising"
    if delta_4w is not None and delta_4w < -0.3:
        return "post_peak_falling"
    if wow is not None and wow >= 0:
        return "pre_peak_rising"
    return "post_peak_falling"


def pick_dominant(covid: float, flu: float, rsv: float) -> str:
    vals = {"covid": covid, "flu": flu, "rsv": rsv}
    # tie-break preference order: covid > flu > rsv (apply when within ε)
    best_key = None
    best_val = -1e18
    for k in PATHOGEN_TIE_ORDER:
        if vals[k] > best_val + 1e-9:
            best_val = vals[k]
            best_key = k
    return PATHOGEN_LABELS[best_key]


def classify_drivers(week_ending: str, dominant: str, covid: float, flu: float,
                     rsv: float, combined: float, delta_4w: float | None,
                     season_phase: str) -> list[str]:
    month = int(week_ending.split("-")[1])
    out: list[str] = []

    # off-season baseline
    if season_phase == "off_season":
        out.append("off_season_baseline")

    # dominant-pathogen-keyed
    if dominant == "influenza":
        if month in (12, 1, 2):
            out.append("influenza_a_season")
        if month in (3, 4):
            out.append("influenza_b_late_season")
        # extra spike: very high flu
        if flu >= 7.0:
            out.append("elderly_hospitalization_surge")
    if dominant == "rsv":
        out.append("rsv_pediatric_wave")
        if rsv >= 1.0 and month in (10, 11, 12, 1):
            out.append("pediatric_hospitalization_surge")
    if dominant == "covid_19":
        if month in (6, 7, 8, 9):
            out.append("covid_summer_wave")
        if month in (12, 1, 2):
            out.append("covid_winter_wave")
        if month in (10, 11) and covid >= 1.5:
            out.append("waning_immunity")
        if covid >= 4.0:
            out.append("elderly_hospitalization_surge")

    # calendar windows
    if month in (12, 1):
        out.append("holiday_mixing")
    if month in (8, 9):
        out.append("back_to_school")
    if month == 1:
        out.append("school_reopening")
    if month in (10, 11) and season_phase in ("pre_peak_rising", "peak_active"):
        out.append("vaccine_uptake_gap")

    # co-circulation: when 2+ pathogens have meaningful share (>= 25%)
    if combined > 0:
        shares = [covid / combined, flu / combined, rsv / combined]
        if sum(1 for s in shares if s >= 0.25) >= 2:
            out.append("cocirculation")

    # deduplicate, preserve order
    seen = set()
    deduped: list[str] = []
    for d in out:
        if d not in seen:
            seen.add(d)
            deduped.append(d)
        if len(deduped) >= 5:
            break

    # fallbacks
    fallbacks = ["cocirculation", "other"]
    for fb in fallbacks:
        if len(deduped) >= 2:
            break
        if fb not in deduped:
            deduped.append(fb)
    return deduped[:5]


def classify_outlook(delta_4w: float | None, season_phase: str) -> str:
    if delta_4w is None:
        return "unclear"
    if delta_4w > 1.0:
        return "rising"
    if delta_4w < -1.0:
        return "falling"
    if abs(delta_4w) <= 0.3 and season_phase == "off_season":
        return "stable"
    return "unclear"


# ------------------------------- renderers ------------------------------

def render_report(week: str, combined: float, season_phase: str,
                         dominant: str, drivers: list[str], outlook: str) -> str:
    dr = ", ".join(d.replace("_", " ") for d in drivers)
    return (
        f"For the week ending {week}, RESP-NET combined hospitalization rate "
        f"ran {combined:.2f}/100k ({season_phase}). "
        f"{dominant.replace('_', ' ').upper() if dominant == 'rsv' else dominant.replace('_', ' ').capitalize()} "
        f"led the three networks. Drivers: {dr}. "
        f"Forward outlook: {outlook}."
    )


def render_evidence(week: str, dominant: str, prior_row: dict | None,
                    prior4_row: dict | None) -> list[dict]:
    evid: list[dict] = []
    if prior_row is not None:
        evid.append({
            "observation": (
                f"Prior reporting week {prior_row['week_ending']} combined RESP-NET "
                f"rate was {prior_row['combined_rate_per_100k']}/100k, "
                f"establishing the recent trajectory."
            ),
            "evidence_reference": (
                f"timeseries.csv row {prior_row['week_ending']} — "
                f"combined_rate_per_100k = {prior_row['combined_rate_per_100k']}"
            ),
        })
    if prior_row is not None:
        # Per-pathogen
        dom_key = {"covid_19": "covid_rate_per_100k",
                   "influenza": "flu_rate_per_100k",
                   "rsv": "rsv_rate_per_100k"}[dominant]
        evid.append({
            "observation": (
                f"Prior reporting week {prior_row['week_ending']} "
                f"{dominant.replace('_', ' ')} rate was "
                f"{prior_row[dom_key]}/100k, confirming the recent lead-pathogen "
                f"trajectory."
            ),
            "evidence_reference": (
                f"timeseries.csv row {prior_row['week_ending']} — "
                f"{dom_key} = {prior_row[dom_key]}"
            ),
        })
    if prior4_row is not None:
        evid.append({
            "observation": (
                f"Four weeks before, on {prior4_row['week_ending']}, the combined "
                f"rate was {prior4_row['combined_rate_per_100k']}/100k, "
                f"anchoring the 4-week delta direction."
            ),
            "evidence_reference": (
                f"timeseries.csv row {prior4_row['week_ending']} — "
                f"combined_rate_per_100k = {prior4_row['combined_rate_per_100k']}"
            ),
        })
    if len(evid) < 2:
        net_name = {"covid_19": "COVID-NET",
                    "influenza": "FluSurv-NET",
                    "rsv": "RSV-NET"}[dominant]
        evid.append({
            "observation": (
                "Prior-period RESP-NET extended history provides the trailing "
                "context for the leading network."
            ),
            "evidence_reference": (
                f"gt_source/{net_name}.csv — prior-period context "
                f"(history through {prior_row['week_ending'] if prior_row else week})"
            ),
        })
    return evid


def render_gt_evidence_md(week: str, gt: dict, prior_row: dict | None,
                          prior4_row: dict | None) -> str:
    drivers_list = "\n".join(f"  - `{d}`" for d in gt["key_drivers"])
    out = (
        f"# Evidence — CDC RESP-NET week ending {week}\n"
        f"\n"
        f"## Per-answer-field citations\n"
        f"\n"
        f"- **combined_rate_per_100k** -> `{gt['combined_rate_per_100k']}`\n"
        f"  - Sourced from timeseries.csv row {week}: combined_rate_per_100k = {gt['combined_rate_per_100k']}\n"
        f"- **season_phase** -> `{gt['season_phase']}`\n"
        f"  - Classified from combined_rate_per_100k level and combined_4w_delta.\n"
        f"- **dominant_pathogen** -> `{gt['dominant_pathogen']}`\n"
        f"  - Argmax of {{covid_rate_per_100k, flu_rate_per_100k, rsv_rate_per_100k}} in row {week}.\n"
        f"- **key_drivers** -> {gt['key_drivers']}\n"
        f"{drivers_list}\n"
        f"  - Heuristic classifier weighs leading pathogen, magnitude, season phase, and month-of-year.\n"
        f"- **outlook_direction_next_period** -> `{gt['outlook_direction_next_period']}`\n"
        f"  - Inferred from combined_4w_delta and season_phase.\n"
        f"\n"
        f"## CSV-grounded numeric tokens\n"
        f"\n"
        f"- combined_rate_per_100k = {gt['combined_rate_per_100k']} (timeseries.csv row {week})\n"
    )
    if prior_row is not None:
        out += (
            f"- prior reporting week {prior_row['week_ending']}: "
            f"combined_rate_per_100k = {prior_row['combined_rate_per_100k']} "
            f"(timeseries.csv row {prior_row['week_ending']})\n"
        )
    if prior4_row is not None:
        out += (
            f"- four reporting weeks prior {prior4_row['week_ending']}: "
            f"combined_rate_per_100k = {prior4_row['combined_rate_per_100k']} "
            f"(timeseries.csv row {prior4_row['week_ending']})\n"
        )
    return out


def render_question_md(week_ending: str, template: str) -> str:
    d = datetime.strptime(week_ending, "%Y-%m-%d")
    week_label_long = d.strftime("%B %-d, %Y")
    return (
        template
        .replace("{{week_label_long}}", week_label_long)
        .replace("{{week_ending}}", week_ending)
    )


# ------------------------------- _step_gt ----------------------------------

def _step_gt() -> int:
    raw_path = TS_SOURCE / "respnet_raw.csv"
    rows = list(csv.DictReader(raw_path.open()))
    joined = join_weekly(rows)
    full = build_full_history(joined)
    by_week = {r["week_ending"]: r for r in full}

    INSTANCES.mkdir(parents=True, exist_ok=True)
    template_path = ENV / "question_template.md"
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
    schema_path = ENV / "answer_schema.json"

    weeks = target_weeks(joined)
    print(f"Target weeks ({len(weeks)}): {weeks}")

    dist_dom = Counter()
    dist_phase = Counter()
    dist_outlook = Counter()

    for week in weeks:
        if week not in by_week:
            print(f"WARN: missing data for {week}", file=sys.stderr)
            continue
        row = by_week[week]
        covid = row["covid_rate_per_100k"]
        flu = row["flu_rate_per_100k"]
        rsv = row["rsv_rate_per_100k"]
        combined = row["combined_rate_per_100k"]
        d4 = row["combined_4w_delta"]
        wow = row["combined_wow_delta"]

        phase = classify_season_phase(combined, d4, wow)
        dominant = pick_dominant(covid, flu, rsv)
        drivers = classify_drivers(week, dominant, covid, flu, rsv,
                                   combined, d4, phase)
        outlook = classify_outlook(d4, phase)

        # Find prior row in joined-week sequence
        all_weeks_sorted = sorted(by_week.keys())
        idx = all_weeks_sorted.index(week)
        prior_row = by_week[all_weeks_sorted[idx - 1]] if idx >= 1 else None
        prior4_row = by_week[all_weeks_sorted[idx - 4]] if idx >= 4 else None

        gt = {
            "report_week_ending": week,
            "combined_rate_per_100k": round(combined, 2),
            "season_phase": phase,
            "dominant_pathogen": dominant,
            "key_drivers": drivers,
            "outlook_direction_next_period": outlook,
            "report": render_report(
                week, combined, phase, dominant, drivers, outlook),
            "supporting_evidence": render_evidence(week, dominant, prior_row, prior4_row),
        }
        ann = {k: v for k, v in gt.items() if k != "report_week_ending"}

        inst_dir = INSTANCES / week
        inst_dir.mkdir(parents=True, exist_ok=True)
        write_csv_for_period(full, inst_dir / "timeseries.csv", week)
        (inst_dir / "ground_truth.json").write_text(
            json.dumps(gt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        (inst_dir / "gt_annotations.json").write_text(
            json.dumps(ann, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        (inst_dir / "gt_evidence.md").write_text(
            render_gt_evidence_md(week, gt, prior_row, prior4_row),
            encoding="utf-8",
        )
        (inst_dir / "question.md").write_text(
            render_question_md(week, template), encoding="utf-8",
        )
        if schema_path.exists():
            shutil.copy2(schema_path, inst_dir / "answer_schema.json")

        dist_dom[dominant] += 1
        dist_phase[phase] += 1
        dist_outlook[outlook] += 1

    n = sum(dist_dom.values()) or 1
    def topp(c):
        return 100.0 * max(c.values()) / n if c else 0.0
    print(f"=== V8 distribution (n_instances={n}) ===")
    print(f"dominant_pathogen: {dict(dist_dom)} (top%={topp(dist_dom):.1f})")
    print(f"season_phase: {dict(dist_phase)} (top%={topp(dist_phase):.1f})")
    print(f"outlook_direction_next_period: {dict(dist_outlook)} (top%={topp(dist_outlook):.1f})")
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
