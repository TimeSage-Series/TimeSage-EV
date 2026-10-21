"""Shared helpers for the fred_sahm_rule_recession_state Easy scenario.

Easy-tier state identification: read /root/timeseries.csv (monthly values of
the FRED SAHMCURRENT series, one observation per month, first-of-month
observation_date) and report the latest month's Sahm-rule `category`.

Vocabulary (ordered from calm to alarm):
    normal              — value < 0.30
    elevated_no_signal  — 0.30 <= value < 0.50  (warning zone, no signal yet)
    recession_signal    — value >= 0.50         (Sahm rule has triggered)

The Sahm Rule (Claudia Sahm, 2019) flags the start of a recession when the
3-month moving average of the unemployment rate rises by at least 0.50
percentage points above its minimum during the previous 12 months. The
FRED series SAHMCURRENT publishes this exact statistic monthly; values at
or above 0.50 are interpreted as a recession-onset signal.
"""
from __future__ import annotations
import os
import calendar
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
# Returns columns: observation_date, SAHMCURRENT
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SERIES_ID = "SAHMCURRENT"

# Three-state vocabulary, ordered from calm to alarm.
CATEGORIES = ["normal", "elevated_no_signal", "recession_signal"]

# Classification thresholds (percentage points of unemployment-rate change).
#   normal             : value <  0.30
#   elevated_no_signal : 0.30 <= value < 0.50
#   recession_signal   : value >= 0.50
NORMAL_UPPER             = 0.30   # exclusive
ELEVATED_NO_SIGNAL_UPPER = 0.50   # exclusive
RECESSION_SIGNAL_LOWER   = 0.50   # inclusive (Sahm threshold)


def classify(value: float) -> str:
    """Map a raw SAHMCURRENT value (percentage points) to a categorical state."""
    if value is None:
        raise ValueError("classify(): value is None")
    if value < NORMAL_UPPER:
        return "normal"
    if value < ELEVATED_NO_SIGNAL_UPPER:
        return "elevated_no_signal"
    return "recession_signal"


def month_label(year: int, month: int) -> str:
    """Return month label `YYYY-MNN` (e.g. `2026-M04`)."""
    return f"{year:04d}-M{month:02d}"


def parse_month_label(label: str) -> tuple[int, int]:
    """Parse `YYYY-MNN` into (year, month)."""
    y, m = label.split("-M")
    return int(y), int(m)


def first_of_month(year: int, month: int) -> dt.date:
    """Return the first-of-month date (FRED's observation_date convention)."""
    return dt.date(year, month, 1)


def last_of_month(year: int, month: int) -> dt.date:
    """Return the last-of-month date (useful for question period_end)."""
    _, last_day = calendar.monthrange(year, month)
    return dt.date(year, month, last_day)


def iter_months(start_label: str, end_label: str):
    """Yield (year, month, first_of_month_date) for every month in [start, end]."""
    y0, m0 = parse_month_label(start_label)
    y1, m1 = parse_month_label(end_label)
    cur = dt.date(y0, m0, 1)
    stop = dt.date(y1, m1, 1)
    while cur <= stop:
        yield cur.year, cur.month, cur
        # advance to first of next month
        if cur.month == 12:
            cur = dt.date(cur.year + 1, 1, 1)
        else:
            cur = dt.date(cur.year, cur.month + 1, 1)
