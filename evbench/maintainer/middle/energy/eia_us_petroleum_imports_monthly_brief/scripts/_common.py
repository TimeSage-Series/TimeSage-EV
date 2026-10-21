"""Shared helpers for eia_us_petroleum_imports_monthly_brief."""
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

# 24-month window matches scenario.yaml instance_window
START_LABEL = "2024-03"
END_LABEL = "2026-02"

# Earliest raw month carried in the cumulative CSV (per instance_resources).
EARLIEST_RAW = "2020-01"

# EIA dnav single-XLS that carries the consolidated U.S. crude oil imports
# by country in thousand barrels per day. ~80 country columns plus the
# U.S. total.
DNAV_XLS_URL = (
    "https://www.eia.gov/dnav/pet/xls/"
    "PET_MOVE_IMPCUS_A2_NUS_EPC0_IM0_MBBLPD_M.xls"
)

NAMED_COUNTRIES = ["Canada", "Mexico", "Saudi Arabia", "Iraq", "Colombia"]
ENUM_FOR = {
    "Canada": "canada",
    "Mexico": "mexico",
    "Saudi Arabia": "saudi_arabia",
    "Iraq": "iraq",
    "Colombia": "colombia",
}

TOTAL_COL = "U.S. Imports of Crude Oil (Thousand Barrels per Day)"

def country_col(name: str) -> str:
    return f"U.S. Imports from {name} of Crude Oil (Thousand Barrels per Day)"


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
