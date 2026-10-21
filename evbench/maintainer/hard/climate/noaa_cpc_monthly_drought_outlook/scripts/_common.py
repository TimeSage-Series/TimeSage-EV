"""Shared helpers for the noaa_cpc_monthly_drought_outlook scenario.

The NOAA CPC Monthly Drought Outlook (MDO) is published on the last day
of each month for the following calendar month (e.g. the issue released
on 2025-05-31 is the outlook for June 2025 and is labelled `2025-06`).

We label each instance by the **forecast month** (YYYY-MM, zero-padded).
The companion narrative text file lives at:

    https://www.cpc.ncep.noaa.gov/products/expert_assessment/MDO/archives/
        <forecast_YYYY>/<forecast_MM>/mdo_<mon><yy>_text.txt

where <mon> is the 3-letter lowercase month-of-forecast abbreviation
(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec) and <yy> is the
2-digit year. e.g. forecast for June 2025 -> /2025/06/mdo_jun25_text.txt

The companion time series is the U.S. Drought Monitor (USDM) CONUS
weekly cumulative area-percent in D0..D4. USDM is released every
Thursday and reflects conditions through 7am Tuesday of the same week.
A USDM week is identified by its `week_ending` date (Tuesday). For the
instance whose forecast month is M, we include all USDM weeks whose
`week_ending` falls on-or-before the MDO release date (the last day of
the month preceding M). i.e. timeseries.csv never leaks data from M
itself.
"""
from __future__ import annotations
import os
import calendar
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

# Be polite — two other CPC scenarios may be downloading concurrently.
CPC_SLEEP_SECONDS = 1.0

# USDM CSV API (no auth, public).
USDM_API_BASE = "https://usdmdataservices.unl.edu/api"

# CPC MDO archive URL template.
MDO_ARCHIVE_URL = (
    "https://www.cpc.ncep.noaa.gov/products/expert_assessment/MDO/archives/"
    "{year:04d}/{month:02d}/mdo_{mon}{yy}_text.txt"
)

# Companion HTML wrapper page (current-issue summary) — snapshotted once
# at pass build time so the README and gt_evidence.md have a stable
# top-level companion reference.
MDO_SUMMARY_URL = (
    "https://www.cpc.ncep.noaa.gov/products/expert_assessment/mdo_summary.php"
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,text/plain,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

_MONTH_ABBR_LC = [
    "", "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]


def month_label(year: int, month: int) -> str:
    """Canonical instance label, e.g. 2025-06. Forecast month."""
    return f"{year:04d}-{month:02d}"


def parse_month_label(label: str) -> tuple[int, int]:
    y, m = label.split("-")
    return int(y), int(m)


def last_day_of_month(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def previous_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def release_date_for(forecast_year: int, forecast_month: int) -> dt.date:
    """The MDO for forecast month M is released on the last day of M-1."""
    py, pm = previous_month(forecast_year, forecast_month)
    return last_day_of_month(py, pm)


def archive_url(forecast_year: int, forecast_month: int) -> str:
    return MDO_ARCHIVE_URL.format(
        year=forecast_year,
        month=forecast_month,
        mon=_MONTH_ABBR_LC[forecast_month],
        yy=forecast_year % 100,
    )


def iter_months(start_label: str, end_label: str):
    """Yield (year, month) inclusive for forecast months."""
    y0, m0 = parse_month_label(start_label)
    y1, m1 = parse_month_label(end_label)
    cur = dt.date(y0, m0, 1)
    stop = dt.date(y1, m1, 1)
    while cur <= stop:
        yield cur.year, cur.month
        if cur.month == 12:
            cur = dt.date(cur.year + 1, 1, 1)
        else:
            cur = dt.date(cur.year, cur.month + 1, 1)


def usdm_tuesdays(start: dt.date, end: dt.date):
    """Yield every USDM week_ending (Tuesday) in [start, end] inclusive.

    USDM weeks end on Tuesday; reports drop the following Thursday.
    """
    cur = start
    # advance to the first Tuesday on-or-after `start`
    while cur.weekday() != 1:   # 0=Mon, 1=Tue
        cur += dt.timedelta(days=1)
    while cur <= end:
        yield cur
        cur += dt.timedelta(days=7)


# Canonical CONUS region vocabulary published by this scenario. Agents
# must use these strings exactly. The list spans CONUS plus the three
# non-CONUS regions the MDO consistently discusses (Hawaii, Alaska,
# Puerto Rico) — although the scoring per scenario.yaml is CONUS-only,
# the vocabulary file is shared with format.py so vocabulary drift
# never silently changes meaning.
CONUS_REGIONS = [
    "Pacific Northwest",
    "Southwest",
    "Northern Plains",
    "Southern Plains",
    "Midwest",
    "Northeast",
    "Southeast",
    "Hawaii",
    "Alaska",
    "Puerto Rico",
]
