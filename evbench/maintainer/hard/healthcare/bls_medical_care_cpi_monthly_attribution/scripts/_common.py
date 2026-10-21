"""Shared helpers for bls_medical_care_cpi_monthly_attribution Hard scenario."""
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

# (short_name, FRED series id)
# Headline: CPIMEDSL — Medical Care CPI (BLS).
# Sub-components:
#   CUSR0000SAM1 — Medical Care Commodities
#   CUSR0000SAM2 — Medical Care Services
#   CUSR0000SEMC — Professional Services
#   CUSR0000SEMD — Hospital Services
HEADLINE = ("medical_care", "CPIMEDSL")
SUBCOMPONENTS = [
    ("medical_commodities", "CUSR0000SAM1"),
    ("medical_services",    "CUSR0000SAM2"),
    ("professional_services", "CUSR0000SEMC"),
    ("hospital_services",   "CUSR0000SEMD"),
]
ALL_SERIES = [HEADLINE] + SUBCOMPONENTS

# 24 query months 2024-04 -> 2026-04 (2024-04..2026-04 minus 2025-10).
START_YEAR, START_MONTH = 2024, 4
N_MONTHS_WINDOW = 25
SHUTDOWN_GAP = {"2025-10"}  # BLS October 2025 gov shutdown


def month_iter(start_year: int, start_month: int, n: int):
    y, m = start_year, start_month
    for _ in range(n):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            m = 1
            y += 1


QUERY_MONTHS_ALL = list(month_iter(START_YEAR, START_MONTH, N_MONTHS_WINDOW))
QUERY_MONTHS = [p for p in QUERY_MONTHS_ALL if p not in SHUTDOWN_GAP]
