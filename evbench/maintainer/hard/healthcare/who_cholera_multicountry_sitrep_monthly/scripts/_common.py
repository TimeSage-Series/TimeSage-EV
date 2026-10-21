"""Shared helpers for the who_cholera_multicountry_sitrep_monthly scenario.

The WHO Multi-country outbreak of cholera External Situation Report (renamed
to "Epidemiological update" from issue #33 onward) is published on a roughly
monthly cadence. We label each issue by the calendar month its publication
date falls in (YYYY-MNN, zero-padded) and anchor the period to the last day
of that month so all instances sort chronologically.
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


def month_label(year: int, month: int) -> str:
    """Canonical month label, e.g. 2025-M03. Zero-padded so labels sort."""
    return f"{year:04d}-M{month:02d}"


def parse_month_label(label: str) -> tuple[int, int]:
    y, m = label.split("-M")
    return int(y), int(m)


def last_day_of_month(year: int, month: int) -> dt.date:
    last = calendar.monthrange(year, month)[1]
    return dt.date(year, month, last)


def iter_months(start_label: str, end_label: str):
    """Yield (year, month, last_day_of_month) inclusive."""
    y0, m0 = parse_month_label(start_label)
    y1, m1 = parse_month_label(end_label)
    cur = dt.date(y0, m0, 1)
    stop = dt.date(y1, m1, 1)
    while cur <= stop:
        yield cur.year, cur.month, last_day_of_month(cur.year, cur.month)
        # advance one month
        if cur.month == 12:
            cur = dt.date(cur.year + 1, 1, 1)
        else:
            cur = dt.date(cur.year, cur.month + 1, 1)


# WHO publication pages allow direct PDF download; user-agent is not strictly
# checked but we send a browser-like UA to avoid drive-by 403s.
WHO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
}
