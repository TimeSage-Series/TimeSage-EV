"""Shared helpers for dallas_fed_texas_manufacturing_brief.

Dallas Fed Texas Manufacturing Outlook Survey (TMOS) is a monthly diffusion-
index survey published as a static HTML page at a deterministic URL:

    https://www.dallasfed.org/research/surveys/tmos/<YYYY>/<YYMM>

where <YYMM> is the two-digit year + two-digit month (e.g. 2604 = Apr 2026).
The HTML contains the full report body with sentences like:
  'production index ... jumped 12 points to 19.0'
  'general business activity index fell two points to -2.3'
  'company outlook index rebounded into positive territory, rising seven points to 3.0'
  'employment index was unchanged at 5.7'

28 consecutive months 2024-01..2026-04 verified at build time.
"""
from __future__ import annotations
import os
import calendar
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

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
HEADERS = {"User-Agent": UA, "Accept": "text/html,*/*"}


def html_url_for(year: int, month: int) -> str:
    yy = year % 100
    return f"https://www.dallasfed.org/research/surveys/tmos/{year:04d}/{yy:02d}{month:02d}"


def month_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def month_label_long(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year:04d}"


def iter_months(start_label: str, end_label: str):
    y0, m0 = int(start_label[:4]), int(start_label[5:7])
    y1, m1 = int(end_label[:4]),   int(end_label[5:7])
    while (y0, m0) <= (y1, m1):
        yield y0, m0
        m0 += 1
        if m0 > 12:
            m0 = 1; y0 += 1
