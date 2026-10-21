"""Shared helpers for the eia_wti_crude_oil_price_band_weekly Easy scenario.

Easy-tier state identification: read /root/timeseries.csv (weekly Friday
closes of the FRED DCOILWTICO series — West Texas Intermediate crude
oil daily spot, USD/bbl) and report the latest week's price-band
`category` (low / normal / elevated / extreme).
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

# FRED CSV export. Public, no API key required.
# Returns columns: observation_date, DCOILWTICO
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SERIES_ID = "DCOILWTICO"
SERIES_LONG_NAME = "West Texas Intermediate (WTI) Crude Oil Spot Price"
PRICE_UNIT = "USD/bbl"

# Four-state vocabulary, ordered from low to extreme.
CATEGORIES = ["low", "normal", "elevated", "extreme"]

# Classification thresholds (USD/barrel).
#   low      : price <  $60
#   normal   : $60  <= price <  $90
#   elevated : $90  <= price <  $110
#   extreme  : price >= $110
LOW_UPPER      = 60.0
NORMAL_UPPER   = 90.0
ELEVATED_UPPER = 110.0


def classify(price):
    if price is None: return None
    if price < LOW_UPPER:      return "low"
    if price < NORMAL_UPPER:   return "normal"
    if price < ELEVATED_UPPER: return "elevated"
    return "extreme"


def week_label(date: dt.date) -> str:
    """Return ISO-week label `YYYY-Www` for the given date."""
    iso = date.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def friday_of_iso_week(year: int, week: int) -> dt.date:
    """Return the Friday (ISO weekday 5) of the given ISO year/week."""
    return dt.date.fromisocalendar(year, week, 5)


def iter_weeks(start_label: str, end_label: str):
    """Yield (year, week, friday_date) for every ISO week in [start, end]."""
    def parse(label: str) -> tuple[int, int]:
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


def parse_iso_label(label: str) -> tuple[int, int]:
    y, w = label.split("-W")
    return int(y), int(w)
