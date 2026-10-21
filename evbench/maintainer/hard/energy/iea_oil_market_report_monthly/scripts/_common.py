"""Shared helpers for iea_oil_market_report_monthly.

The IEA Oil Market Report (OMR) is published monthly (typically the 2nd
Tuesday or Wednesday of each month, occasionally shifted). The free version
is the Highlights document (~10-15 pages), publicly hosted on
iea.blob.core.windows.net behind UUID-prefixed paths. We index each issue by
its calendar month label (YYYY-MM) which matches the IEA landing page slug
`oil-market-report-<month>-<year>` (e.g. oil-market-report-april-2026).

The PDF URL convention is:
    https://iea.blob.core.windows.net/assets/<uuid>/-<DDMMM YYYY>_OilMarketReport[_Free_version1].pdf

where <DDMMM> is e.g. 14APR, 12MAR. The UUID is unique per issue and cannot
be derived deterministically; we must scrape the landing HTML to find the
asset link. landing_urls.json records the landing-page URL and (where known)
the direct asset URL as a fallback.
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

# IEA's CloudFront/Azure layer serves PDFs with no auth, but rejects empty UA.
IEA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

IEA_BLOB_BASE = "https://iea.blob.core.windows.net/assets/"
IEA_LANDING_BASE = "https://www.iea.org/reports/oil-market-report-"

_MONTH_NAME = ["", "january", "february", "march", "april", "may", "june",
               "july", "august", "september", "october", "november", "december"]


def iter_months(start_label: str, end_label: str):
    """Yield first-of-month datetime.date from start_label..end_label inclusive."""
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
    """Canonical YYYY-MM label."""
    return f"{d.year:04d}-{d.month:02d}"


def parse_month_label(label: str) -> dt.date:
    y, m = label.split("-")
    return dt.date(int(y), int(m), 1)


def landing_slug(d: dt.date) -> str:
    """oil-market-report-<month>-<year>"""
    return f"{_MONTH_NAME[d.month]}-{d.year}"


def landing_url(d: dt.date) -> str:
    return f"{IEA_LANDING_BASE}{landing_slug(d)}"
