"""Shared helpers for bls_us_health_employment_monthly_brief."""
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

START_LABEL = "2024-03"
END_LABEL = "2026-02"
EARLIEST_RAW = "2022-01"

# FRED graph CSV mirror of BLS CES sub-sector series. No API key needed.
FRED_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="

SERIES = {
    "physicians_offices":  "CES6562110001",  # Offices of physicians
    "hospitals":           "CES6562200001",  # Hospitals
    "nursing_care":        "CES6562300001",  # Nursing & residential care
    "ambulatory_total":    "CES6562100001",  # Ambulatory health care services (total)
    "social_assistance":   "CES6562400001",  # Social assistance
}


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
