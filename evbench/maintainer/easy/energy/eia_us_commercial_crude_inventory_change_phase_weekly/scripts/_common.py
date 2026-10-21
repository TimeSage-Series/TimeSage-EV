"""Shared helpers for the eia_us_commercial_crude_inventory_change_phase_weekly Easy scenario.

Easy-tier state identification: read /root/timeseries.csv (EIA weekly
commercial crude oil stocks excluding SPR, series WCESTUS1, sampled at
the published Friday week-ending date) and report the latest week's
inventory-change `crude_inventory_phase` {build, draw, flat} based on
the week-over-week change in million barrels (MMbbl).

Vocabulary (ordered):
    build — wow_change >= +0.5 MMbbl
    draw  — wow_change <= -0.5 MMbbl
    flat  — else (i.e., -0.5 < wow_change < +0.5 MMbbl)
"""
from __future__ import annotations
import os
import datetime as dt
import sys
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
# Source artifacts now live in one period-organised tree rather than being
# split by which stage reads them. SourceTree routes writes into
# source/<period>/ and flattens the tree back for reads, so the call sites here
# and in format.py are unchanged. GT_SOURCE and TS_SOURCE are the same tree;
# the names are kept so the 60 pipeline scripts need no edits.
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "lib"))
from source_tree import SourceTree  # noqa: E402

_SOURCE = SCENARIO_ROOT / "source"
def _known_periods() -> list:
    """Period names this scenario uses, for placing files in source/<period>/.

    Taken from the source tree's own period folders and from any instances that
    already exist, unioned. Reading only `instances/` breaks on a fresh data
    root — the directory is empty until format runs, so the irregular period
    names (Bank of England's `2023-August03`, ECB's `2023-Dec14`) would have
    nothing to match against and every file would land at the source root.
    """
    names = set()
    for base in (SCENARIO_ROOT / "source", SCENARIO_ROOT / "instances"):
        if base.is_dir():
            names.update(d.name for d in base.iterdir() if d.is_dir())
    return sorted(names, key=len, reverse=True)


_KNOWN_PERIODS = _known_periods()
TS_SOURCE = SourceTree(_SOURCE, _KNOWN_PERIODS)
GT_SOURCE = SourceTree(_SOURCE, _KNOWN_PERIODS)

INSTANCES = SCENARIO_ROOT / "instances"

# EIA Weekly Petroleum Status Report - commercial crude stocks excl. SPR.
EIA_XLS_URL = "https://www.eia.gov/dnav/pet/hist_xls/WCESTUS1w.xls"
SERIES_ID = "WCESTUS1"
SERIES_LONG_NAME = ("Weekly U.S. Ending Stocks excluding SPR of Crude Oil "
                    "(Thousand Barrels)")
UNIT_STOCK_THOUSAND = "thousand barrels"
UNIT_CHANGE = "million barrels"
PAGE_URL = "https://www.eia.gov/petroleum/weekly/"

CATEGORIES = ["build", "draw", "flat"]

# Threshold thresholds in MILLION barrels.
BUILD_THRESHOLD_MMBBL =  0.5   # >= +0.5 MMbbl
DRAW_THRESHOLD_MMBBL  = -0.5   # <= -0.5 MMbbl


def classify(wow_change_mmbbl):
    if wow_change_mmbbl is None:
        return None
    if wow_change_mmbbl >=  BUILD_THRESHOLD_MMBBL: return "build"
    if wow_change_mmbbl <=  DRAW_THRESHOLD_MMBBL:  return "draw"
    return "flat"


def week_label(date: dt.date) -> str:
    iso = date.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def friday_of_iso_week(year: int, week: int) -> dt.date:
    return dt.date.fromisocalendar(year, week, 5)


def iter_weeks(start_label: str, end_label: str):
    def parse(label: str):
        y, w = label.split("-W")
        return int(y), int(w)

    y0, w0 = parse(start_label)
    y1, w1 = parse(end_label)
    cur = friday_of_iso_week(y0, w0)
    stop = friday_of_iso_week(y1, w1)
    while cur <= stop:
        iso = cur.isocalendar()
        yield iso.year, iso.week, cur
        cur += dt.timedelta(days=7)


def excel_serial_to_date(serial) -> dt.date:
    if isinstance(serial, str):
        return dt.date.fromisoformat(serial)
    return (dt.datetime(1899, 12, 30) + dt.timedelta(days=float(serial))).date()


def period_long(year: int, week: int) -> str:
    return f"ISO week {year:04d}-W{week:02d}"
