"""Shared helpers for usda_chicken_layers_yoy_phase_monthly.

The USDA NASS Chickens and Eggs report is a monthly PDF (around the
20th of each month) reporting the prior calendar month's egg
production and average layer flock. The 'Layers on Hand and Eggs
Produced by Type and Molt' table on page 5 or 6 carries a 'Layers
during <month> / Total layers' row with both this-year and prior-year
average flock sizes in 1,000-head precision; signed YoY% is computed
from those two figures.

PDF URL pattern (esmis.nal.usda.gov):
  - recent:  /sites/default/release-files/<id>/ckeg<MMYY>.pdf
  - older:   /sites/default/release-files/<hash>/<hash>/<hash>/ckeg<MMYY>.pdf
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

LANDING_BASE = "https://esmis.nal.usda.gov/publication/chickens-and-eggs"
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

LAYER_PHASE_OPTIONS = ["expansion", "contraction", "steady"]
DEADBAND_PCT = 0.5


def mmyy_to_release_month(mmyy: str) -> tuple[int, int]:
    if len(mmyy) != 4:
        raise ValueError(f"bad mmyy {mmyy!r}")
    mm = int(mmyy[:2])
    yy = int(mmyy[2:])
    year = 2000 + yy if yy < 80 else 1900 + yy
    return year, mm


def release_to_data_month(release_year: int, release_month: int) -> tuple[int, int]:
    if release_month == 1:
        return release_year - 1, 12
    return release_year, release_month - 1


def data_month_to_release(data_year: int, data_month: int) -> tuple[int, int]:
    if data_month == 12:
        return data_year + 1, 1
    return data_year, data_month + 1


def month_to_folder(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def month_label(year: int, month: int) -> str:
    import calendar
    return f"{calendar.month_name[month]} {year:04d}"


def classify_phase(yoy_pct: float) -> str:
    if yoy_pct > DEADBAND_PCT:
        return "expansion"
    if yoy_pct < -DEADBAND_PCT:
        return "contraction"
    return "steady"
