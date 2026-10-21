"""Shared helpers for the hhs_us_hospital_inpatient_occupancy_band_weekly Easy scenario.

Easy-tier state identification: read /root/timeseries.csv (CDC Weekly
Hospital Respiratory Data, jurisdiction='USA', `pctinptbedsocc` —
percent of inpatient beds occupied at US aggregate, MMWR-week-ending
Saturday) and report the latest week's `occupancy_band`
{low, normal, elevated, surge}.

Vocabulary (ordered from low to surge):
    low      — pctinptbedsocc <  70
    normal   — 70  <= pctinptbedsocc <  73
    elevated — 73  <= pctinptbedsocc <  76
    surge    — pctinptbedsocc >= 76

Threshold calibration note: the canonical HHS Hospital Capacity public
talking points used 65/75/85 bands, but in 2024-2026 US aggregate
inpatient occupancy has hugged a tighter 68-77% corridor (post-pandemic
elective-procedure normalization). The 70/73/76 cascade preserves the
"low/normal/elevated/surge" semantics with healthy variability across
the instance window. The thresholds are still fixed numeric thresholds
(not percentile-based), so the rule remains an A1 (state.category)
classification task.
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

# CDC Weekly Hospital Respiratory Data — Metrics by Jurisdiction (Socrata API).
# Public, unauthenticated. Returns CSV/JSON. Column `pctinptbedsocc` is the
# percent of inpatient beds occupied (0-100). Jurisdiction='USA' is the
# national aggregate.
CDC_API_URL = (
    "https://data.cdc.gov/resource/ua7e-t2fy.csv"
    "?$select=weekendingdate,jurisdiction,pctinptbedsocc"
    "&jurisdiction=USA"
    "&$order=weekendingdate%20ASC"
    "&$limit=2000"
)
DATASET_ID = "ua7e-t2fy"
DATASET_NAME = ("Weekly Hospital Respiratory Data (HRD) Metrics by "
                "Jurisdiction, National Healthcare Safety Network")
PAGE_URL = ("https://data.cdc.gov/Public-Health-Surveillance/"
            "Weekly-Hospital-Respiratory-Data-HRD-Metrics-by-Ju/ua7e-t2fy")
UNIT = "percent"

CATEGORIES = ["low", "normal", "elevated", "surge"]

# Threshold cascade (percent of inpatient beds occupied, 0-100).
LOW_UPPER       = 70.0   # exclusive upper bound for 'low'
NORMAL_UPPER    = 73.0   # exclusive upper bound for 'normal'
ELEVATED_UPPER  = 76.0   # exclusive upper bound for 'elevated'


def classify(pct):
    if pct is None:
        return None
    if pct < LOW_UPPER:      return "low"
    if pct < NORMAL_UPPER:   return "normal"
    if pct < ELEVATED_UPPER: return "elevated"
    return "surge"


def week_label(saturday: dt.date) -> str:
    """Return ISO-week label `YYYY-Www` for the Friday of the same MMWR week.

    HHS/CDC publishes a Saturday week-ending date (MMWR week convention).
    Our scenario portfolio uses the ISO-week label `YYYY-Www` where the
    Saturday of that ISO week is `week_ending`. ISO week labels are
    derived from the Saturday's date (which is ISO weekday 6)."""
    iso = saturday.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def saturday_of_iso_week(year: int, week: int) -> dt.date:
    """Return the Saturday (ISO weekday 6) of the given ISO year/week."""
    return dt.date.fromisocalendar(year, week, 6)


def iter_weeks(start_label: str, end_label: str):
    """Yield (year, week, saturday_date) for every ISO week in [start, end]."""
    def parse(label: str) -> tuple[int, int]:
        y, w = label.split("-W")
        return int(y), int(w)

    y0, w0 = parse(start_label)
    y1, w1 = parse(end_label)
    cur = saturday_of_iso_week(y0, w0)
    stop = saturday_of_iso_week(y1, w1)
    while cur <= stop:
        iso = cur.isocalendar()
        yield iso.year, iso.week, cur
        cur += dt.timedelta(days=7)


def period_long(year: int, week: int) -> str:
    return f"ISO week {year:04d}-W{week:02d}"
