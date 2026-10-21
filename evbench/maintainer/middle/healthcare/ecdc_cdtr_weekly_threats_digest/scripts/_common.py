"""Shared helpers for the ecdc_cdtr_h5n1 scenario scripts."""
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

# CDTR uses ISO weeks (Mon-Sun, ISO 8601). Saturday = day 6.
def iso_saturday(year: int, week: int) -> dt.date:
    monday = dt.date.fromisocalendar(year, week, 1)
    return monday + dt.timedelta(days=5)

def iso_week_label(year: int, week: int) -> str:
    return f"{year:04d}-W{week:02d}"

def parse_label(label: str) -> tuple[int, int]:
    y, w = label.split("-W")
    return int(y), int(w)

def iter_iso_weeks(start: str, end: str):
    y0, w0 = parse_label(start); y1, w1 = parse_label(end)
    cur = dt.date.fromisocalendar(y0, w0, 1)  # Monday of start week
    stop = dt.date.fromisocalendar(y1, w1, 1)
    while cur <= stop:
        iso = cur.isocalendar()
        yield iso.year, iso.week, iso_saturday(iso.year, iso.week)
        cur += dt.timedelta(days=7)

# ECDC CDTR allows direct PDF download; user-agent is not strictly checked.
ECDC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
}
