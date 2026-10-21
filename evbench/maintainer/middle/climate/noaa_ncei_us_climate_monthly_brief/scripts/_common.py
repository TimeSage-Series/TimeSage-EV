"""Shared helpers for the noaa_ncei_us_climate_monthly_brief scenario.

The NOAA NCEI "Assessing the Global Climate in <Month> <Year>" news article
serves as both the raw time-series source AND the ground-truth artifact for
this scenario (Middle tier — descriptive data brief). One artifact per
month, named YYYYMM where MM ∈ 01..12 (annual rollup YYYYMM=YYYY13 is OUT
OF SCOPE).
"""
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

# Canonical URL pattern for the NCEI monthly global climate brief.
# Verified live for 202401, 202406, 202408 at Stage 1 (apis.yaml).
NCEI_URL_PATTERN = "https://www.ncei.noaa.gov/news/national-climate-{period}"

# Climate at a Glance time-series (CSV) used as a cross-check / companion.
# Each NCEI monthly brief's headline anomaly is the value rendered in that
# month's row of these CSVs. We do NOT pull from these in this scenario —
# the agent works only off the parsed brief text — but we cite them in
# gt_evidence.md as the public traceability anchor for V4.
CAAG_GLOBAL_TS = (
    "https://www.ncei.noaa.gov/access/monitoring/"
    "climate-at-a-glance/global/time-series"
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Safari/605.1.15"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

REQUEST_SLEEP_SEC = 0.5   # politeness gap between NCEI HTTP calls.


# --- period helpers ---------------------------------------------------------

def period_to_yyyymm(period: str) -> str:
    """Convert a 'YYYY-MM' instance label to a 'YYYYMM' URL fragment."""
    y, m = period.split("-")
    return f"{int(y):04d}{int(m):02d}"


def yyyymm_to_period(yyyymm: str) -> str:
    """Convert a 'YYYYMM' URL fragment back to 'YYYY-MM'."""
    return f"{yyyymm[:4]}-{yyyymm[4:6]}"


def parse_period(s: str) -> dt.date:
    """Parse 'YYYY-MM' to a date pegged to the 15th of that month."""
    y, m = s.split("-")
    return dt.date(int(y), int(m), 15)


def iter_periods(start: str, end: str):
    """Yield 'YYYY-MM' month labels from start through end inclusive.

    Excludes annual rollups (the per-brief YYYY13 case never appears in
    this range since MM ∈ 01..12).
    """
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            m = 1; y += 1


def month_name_long(period: str) -> str:
    """'2024-06' -> 'June 2024'."""
    y, m = (int(x) for x in period.split("-"))
    return f"{dt.date(y, m, 1).strftime('%B')} {y}"


def previous_period(period: str) -> str:
    y, m = (int(x) for x in period.split("-"))
    m -= 1
    if m == 0:
        m = 12; y -= 1
    return f"{y:04d}-{m:02d}"


def n_months_before(period: str, n: int) -> str:
    y, m = (int(x) for x in period.split("-"))
    total = y * 12 + (m - 1) - n
    y2, m2 = divmod(total, 12)
    return f"{y2:04d}-{m2 + 1:02d}"
