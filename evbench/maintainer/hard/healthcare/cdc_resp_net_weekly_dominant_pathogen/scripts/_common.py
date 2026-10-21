"""Shared helpers for cdc_resp_net_weekly_dominant_pathogen."""
from __future__ import annotations
import os
from pathlib import Path

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



SCENARIO_ROOT = _scenario_data_dir(__file__)
TS_SOURCE = SCENARIO_ROOT / "timeseries_source"
GT_SOURCE = SCENARIO_ROOT / "gt_source"
INSTANCES = SCENARIO_ROOT / "instances"
ENV = SCENARIO_ROOT / "environment"

CDC_SOQL_URL = (
    "https://data.cdc.gov/resource/kvib-3txy.csv?"
    "$where=site='Overall' AND age_group='Overall' AND sex='Overall' "
    "AND race_ethnicity='Overall' AND rate_type='Observed'"
    "&$order=week_ending_date ASC&$limit=5000"
)

NETWORKS = ("COVID-NET", "FluSurv-NET", "RSV-NET")
NETWORK_TO_KEY = {
    "COVID-NET":    "covid",
    "FluSurv-NET":  "flu",
    "RSV-NET":      "rsv",
}
PATHOGEN_LABELS = {
    "covid": "covid_19",
    "flu":   "influenza",
    "rsv":   "rsv",
}
PATHOGEN_TIE_ORDER = ["covid", "flu", "rsv"]  # most-preferred first

# 24 weekly instances, evenly spaced across 2024-04..2026-04 valid-data weeks
# (off-season weeks where FluSurv/RSV pause observed reporting are excluded
# naturally because such weeks aren't in the joined dataset).
N_INSTANCES = 24
WINDOW_START = "2024-04-01"
WINDOW_END = "2026-04-30"


def join_weekly(rows):
    """Join the raw long-form rows into a wide dict keyed by week_ending_date.
    Returns {date: {network: rate}}.
    """
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        net = r.get("surveillance_network", "")
        if net not in NETWORKS:
            continue
        w = r.get("week_ending_date", "")
        try:
            rate = float(r.get("weekly_rate") or "")
        except (TypeError, ValueError):
            continue
        out.setdefault(w, {})[net] = rate
    return out


def all_valid_weeks(joined):
    return sorted(w for w, d in joined.items() if all(k in d for k in NETWORKS))


def target_weeks(joined):
    valid = [w for w in all_valid_weeks(joined)
             if WINDOW_START <= w <= WINDOW_END]
    if len(valid) < N_INSTANCES:
        return valid
    idxs = [round(i * (len(valid) - 1) / (N_INSTANCES - 1)) for i in range(N_INSTANCES)]
    return [valid[i] for i in sorted(set(idxs))]
