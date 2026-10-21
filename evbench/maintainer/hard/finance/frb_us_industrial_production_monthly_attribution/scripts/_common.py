"""Shared helpers for frb_us_industrial_production_monthly_attribution Hard scenario."""
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

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"

SERIES_ID = "INDPRO"

# 24 query months from 2024-04 through 2026-03 (inclusive).
START_YEAR, START_MONTH = 2024, 4
N_INSTANCES = 24

EARLIEST_TS_PERIOD = "2017-01"


def month_iter(start_year: int, start_month: int, n: int):
    y, m = start_year, start_month
    for _ in range(n):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            m = 1
            y += 1


QUERY_MONTHS = list(month_iter(START_YEAR, START_MONTH, N_INSTANCES))
