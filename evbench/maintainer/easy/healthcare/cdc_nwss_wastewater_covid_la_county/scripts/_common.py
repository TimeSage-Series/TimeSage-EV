"""Shared helpers for the cdc_nwss_wastewater_*_la_county Easy scenarios.

Each scenario is a single-site, single-pathogen state-identification task:
read /root/timeseries.csv, return the week-over-week direction of `site_wval`.
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

# CDC NWSS atcp-73re: Wastewater Viral Activity Level for SARS-CoV-2,
# Influenza A and RSV. The answer is the WoW direction of site_wval.
SOCRATA_DATASET = "atcp-73re"
SOCRATA_URL = f"https://data.cdc.gov/resource/{SOCRATA_DATASET}.json"

# This scenario is parameterized below. Each of the three Easy scenarios
# overrides PATHOGEN_TARGET via its own _common.py.
TARGET_SITE = "ID:113"           # Los Angeles + Ventura, CA (4M pop served)
TARGET_STATE = "California"
PATHOGEN_TARGET = "SARS-CoV-2"

# The Socrata API uses a "Mozilla/5.0"-ish UA by default; no exotic headers needed.



def week_label(date: dt.date) -> str:
    """Return ISO-week label `YYYY-Www` for a Saturday week-ending date.

    NWSS week_end columns are Saturday-ending. We use the ISO week containing
    that Saturday as the label — consistent with scenario 1's convention.
    """
    iso = date.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def iter_weeks(start_label: str, end_label: str):
    """Yield (year, week, saturday_date) for every ISO week in [start, end]."""
    def parse(label: str) -> tuple[int, int]:
        y, w = label.split("-W"); return int(y), int(w)
    y0, w0 = parse(start_label); y1, w1 = parse(end_label)
    # Compute Saturday of each ISO week from start to end inclusive.
    cur = dt.date.fromisocalendar(y0, w0, 6)
    stop = dt.date.fromisocalendar(y1, w1, 6)
    while cur <= stop:
        iso = cur.isocalendar()
        yield iso.year, iso.week, cur
        cur += dt.timedelta(days=7)
