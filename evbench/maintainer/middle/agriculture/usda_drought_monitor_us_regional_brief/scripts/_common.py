"""Shared helpers for the usda_drought_monitor_us_regional_brief scenario.

Middle-tier USDM scenario at the CONUS / 6-region aggregate level. The
agent reads the cumulative national time series + the weekly Summary.aspx
narrative and produces a structured digest covering:
  - headline national drought category
  - which region the narrative singles out
  - week-over-week direction of total drought area
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

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

# Headline category threshold for the CONUS rollup. National-scale drought
# is less concentrated than state-level — use a higher threshold.
CONUS_HEADLINE_THRESHOLD = 25.0

USDM_REGIONS = ["West", "High Plains", "Midwest", "South", "Southeast", "Northeast"]


def usdm_tuesday(year: int, week: int) -> dt.date:
    jan4 = dt.date(year, 1, 4)
    monday_w1 = jan4 - dt.timedelta(days=jan4.isoweekday() - 1)
    return monday_w1 + dt.timedelta(days=(week - 1) * 7 + 1)


def iso_label(year: int, week: int) -> str:
    return f"{year:04d}-W{week:02d}"


def date_to_iso_label(d: dt.date) -> str:
    iy, iw, _ = d.isocalendar()
    return f"{iy:04d}-W{iw:02d}"


def parse_iso_label(label: str) -> tuple[int, int]:
    y, w = label.split("-W")
    return int(y), int(w)


def iter_weeks(start_label: str, end_label: str):
    y0, w0 = parse_iso_label(start_label)
    y1, w1 = parse_iso_label(end_label)
    cur = usdm_tuesday(y0, w0)
    stop = usdm_tuesday(y1, w1)
    while cur <= stop:
        iy, iw, _ = cur.isocalendar()
        yield iy, iw, cur
        cur += dt.timedelta(days=7)
