"""Shared helpers for bls_jolts_healthcare_monthly_brief."""
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

START_LABEL = "2024-02"
END_LABEL = "2026-02"
EARLIEST_RAW = "2022-01"

# FRED-backed JOLTS series for Health Care & Social Assistance (NAICS 62).
# JTS = seasonally-adjusted; JOL/HIL/QUL/TSL are levels in thousands.
FRED_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="

SERIES = {
    "job_openings_thousands":   "JTS6200JOL",  # Job openings
    "hires_thousands":          "JTS6200HIL",  # Hires
    "quits_thousands":          "JTS6200QUL",  # Quits
    "total_separations_thousands": "JTS6200TSL",  # Total separations
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


def long_month_label(label: str) -> str:
    y, m = (int(x) for x in label.split("-"))
    return f"{MONTH_NAMES[m - 1]} {y}"
