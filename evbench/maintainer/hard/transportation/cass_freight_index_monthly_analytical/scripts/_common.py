"""Shared helpers for cass_freight_index_monthly_analytical."""
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
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


def cass_slug(d: dt.date) -> str:
    """URL slug used by cassinfo.com, e.g. 'march-2026'."""
    return f"{MONTH_NAMES[d.month - 1]}-{d.year:04d}"


def cass_url(d: dt.date) -> str:
    return (
        "https://www.cassinfo.com/freight-audit-payment/"
        f"cass-transportation-indexes/{cass_slug(d)}"
    )
