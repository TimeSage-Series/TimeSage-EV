"""Shared helpers for usda_cold_storage_butter_band_monthly.

The USDA NASS Cold Storage report is a monthly PDF (around the 23rd-
25th of each month) reporting end-of-prior-month US butter and cheese
stocks, frozen poultry, red meat, fruit, vegetable, and dairy
inventory. We harvest the headline US total butter stocks figure
(top-of-page-4 dairy table, third numeric column = current data
month) and standardise it into a 4-band classification against a
same-calendar-month 5-year reference window.

Release month vs data month: cost<MMYY>.pdf is RELEASED in month MM/YY
and reports stocks for DATA MONTH MM-1 / YY (e.g. cost0426.pdf
released April 2026 reports March 2026 stocks). We anchor each
instance to the DATA MONTH (folder name YYYY-MM = data month).

PDF URL pattern (esmis.nal.usda.gov):
  - recent:  /sites/default/release-files/<id>/cost<MMYY>.pdf
  - older:   /sites/default/release-files/<hash>/<hash>/<hash>/cost<MMYY>.pdf
Both families are 200 OK with no auth; we scrape the listing pages
0..8 to harvest the exact URL for each MMYY of interest.
"""
from __future__ import annotations
import os
import datetime as dt
import statistics
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

LANDING_BASE = "https://esmis.nal.usda.gov/publication/cold-storage"
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

BUTTER_BAND_OPTIONS = ["tight", "low", "normal", "heavy"]


def mmyy_to_release_month(mmyy: str) -> tuple[int, int]:
    """Convert filename MMYY tag (e.g. '0426') to (release_year, release_month)."""
    if len(mmyy) != 4:
        raise ValueError(f"bad mmyy {mmyy!r}")
    mm = int(mmyy[:2])
    yy = int(mmyy[2:])
    year = 2000 + yy if yy < 80 else 1900 + yy
    return year, mm


def release_to_data_month(release_year: int, release_month: int) -> tuple[int, int]:
    """Data month is the calendar month PRIOR to the release month."""
    if release_month == 1:
        return release_year - 1, 12
    return release_year, release_month - 1


def data_month_to_release(data_year: int, data_month: int) -> tuple[int, int]:
    """Release month is the calendar month AFTER the data month."""
    if data_month == 12:
        return data_year + 1, 1
    return data_year, data_month + 1


def data_month_to_release_mmyy(data_year: int, data_month: int) -> str:
    rel_y, rel_m = data_month_to_release(data_year, data_month)
    yy = rel_y - 2000
    return f"{rel_m:02d}{yy:02d}"


def month_to_folder(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def month_label(year: int, month: int) -> str:
    import calendar
    return f"{calendar.month_name[month]} {year:04d}"


def classify_band(stocks: float, mn: float, mean: float, sigma: float) -> str:
    if stocks < mn:
        return "tight"
    if stocks < mean - 0.5 * sigma:
        return "low"
    if stocks < mean + 0.5 * sigma:
        return "normal"
    return "heavy"
