"""Shared helpers for usda_fas_world_agricultural_production_monthly_attribution."""
from __future__ import annotations
import os
import datetime as dt
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
}

START_LABEL = "2024-01"
END_LABEL = "2026-03"
EARLIEST_RAW = "2022-01"

# FRED-backed timeseries for global production proxies (per-commodity world stocks/production
# is published by USDA WAOB only in PSD database). We pull WAOB key world series via FRED:
# - PWHEAMTUSDM   Global wheat price (USD/MT) — proxy for tightness
# - PMAIZMTUSDM   Global maize price (USD/MT)
# - PSOYBUSDM     Global soybean price (USD/MT)
# - PRICENPQUSDM  Global rice price (USD/MT)
# These prices are NOT the WAP production numbers themselves; they are co-traded indicators
# the WAP bulletin contextualizes. The WAP PDFs are the primary GT narrative source.
FRED_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="

SERIES = {
    "wheat_price_usd_mt":   "PWHEAMTUSDM",
    "maize_price_usd_mt":   "PMAIZMTUSDM",
    "soybean_price_usd_mt": "PSOYBUSDM",
    "rice_price_usd_mt":    "PRICENPQUSDM",
}

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def iter_months(start_label: str, end_label: str):
    sy, sm = (int(x) for x in start_label.split("-"))
    ey, em = (int(x) for x in end_label.split("-"))
    cur = dt.date(sy, sm, 1)
    stop = dt.date(ey, em, 1)
    while cur <= stop:
        yield cur
        if cur.month == 12:
            cur = dt.date(cur.year + 1, 1, 1)
        else:
            cur = dt.date(cur.year, cur.month + 1, 1)


def month_label(d: dt.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def prior_month(label: str) -> str:
    y, m = (int(x) for x in label.split("-"))
    if m == 1:
        return f"{y - 1:04d}-12"
    return f"{y:04d}-{m - 1:02d}"


def long_month_label(label: str) -> str:
    y, m = (int(x) for x in label.split("-"))
    return f"{MONTH_NAMES[m - 1]} {y}"
