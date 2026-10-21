"""Shared helpers for usda_cattle_on_feed_placements_yoy.

The USDA NASS Cattle on Feed report is a monthly PDF (around the 20th of
each month) reporting U.S. feedlot inventory, placements, and marketings
for the prior month. The headline 'Placements in feedlots' figure is
quoted with an explicit year-over-year comparison ('<X> percent above
<prior year>' / '<X> percent below <prior year>' / 'equal to <prior
year>'), which we extract and classify into a 3-option enum for the
Easy-tier state-identification task.

Release month vs data month: a report released in month X covers data
from month X-1 (e.g. cofd0326.pdf was released 2026-03-20 and reports
February 2026 placements). We anchor each instance to the RELEASE month
(matching the filename's MMYY tag) so the agent's 'as of' temporal
context aligns with what is observable on the publication date.

PDF URLs are listed on https://esmis.nal.usda.gov/publication/cattle-feed
with two URL families:
  - recent reports: /sites/default/release-files/<numeric-id>/cofd<MMYY>.pdf
  - older reports:  /sites/default/release-files/m326m174z/<hash>/<hash>/cofd<MMYY>.pdf
Both are 200 OK with no auth; we scrape the listing pages to harvest the
exact URL for each MMYY of interest.
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

#: First release in the series (scenario.json coverage.series_first). Earlier
#: releases are on the landing pages too, but the released timeseries.csv files
#: start here, so the history window must not reach further back.
SERIES_FIRST = "2022-12"

LANDING_BASE = "https://esmis.nal.usda.gov/publication/cattle-feed"
ESMIS_BASE   = "https://esmis.nal.usda.gov"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

PLACEMENTS_YOY_OPTIONS = ["above_prior_year", "below_prior_year", "equal_to_prior_year"]


def mmyy_to_release_month(mmyy: str) -> tuple[int, int]:
    """Convert filename MMYY tag (e.g. '0326') to (release_year, release_month)."""
    if len(mmyy) != 4:
        raise ValueError(f"bad mmyy {mmyy!r}")
    mm = int(mmyy[:2])
    yy = int(mmyy[2:])
    year = 2000 + yy if yy < 80 else 1900 + yy
    return year, mm


def release_month_to_folder(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def release_month_label(year: int, month: int) -> str:
    import calendar
    return f"{calendar.month_name[month]} {year:04d}"


def data_month_label(release_year: int, release_month: int) -> str:
    """Data month is the calendar month PRIOR to the release month."""
    import calendar
    if release_month == 1:
        y, m = release_year - 1, 12
    else:
        y, m = release_year, release_month - 1
    return f"{calendar.month_name[m]} {y:04d}"
