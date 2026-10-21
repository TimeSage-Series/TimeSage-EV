"""Shared helpers for the noaa_cpc_pna_phase_monthly scenario.

The Pacific/North American (PNA) teleconnection pattern is a NOAA CPC
index summarising a mid-latitude wave-train circulation pattern over
the Pacific and North America. It is a DIFFERENT atmospheric
phenomenon from the Arctic Oscillation (AO):

  - AO  : Northern-Hemisphere annular pattern (sea-level pressure
          north of 20degN, polar-vortex strength).
  - PNA : Pacific/North American mid-latitude wave train (500-hPa
          height anomalies; ridge over western North America +
          trough over eastern North America vs the reverse).

We co-host this scenario alongside the AO one as an independent Easy
categorical-state scenario in the climate domain. Both apply a
+/-0.5 sigma threshold to a standardised monthly index, but the
underlying physical phenomena, geographic footprints, and enum
vocabularies differ.

PNA monthly values are published as a plain-ASCII text file
maintained since 1950 by the CPC, with each line carrying the year,
month, and monthly mean PNA index value standardised against the
1950-2001 base period (file token "b5001" in the URL).
"""
from __future__ import annotations
import os
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

PNA_TXT_URL = (
    "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/"
    "norm.pna.monthly.b5001.current.ascii"
)

PNA_DASHBOARD_URL = (
    "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/pna.shtml"
)

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

POS_THRESHOLD = 0.5
NEG_THRESHOLD = -0.5

PNA_PHASE_OPTIONS = ["positive_phase", "negative_phase", "neutral"]


def classify_phase(pna_value: float) -> str:
    if pna_value >= POS_THRESHOLD:
        return "positive_phase"
    if pna_value <= NEG_THRESHOLD:
        return "negative_phase"
    return "neutral"


def month_to_folder(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def month_label(year: int, month: int) -> str:
    import calendar
    return f"{calendar.month_name[month]} {year:04d}"


def parse_pna_ascii(text: str) -> list[dict]:
    """Parse the PNA monthly ascii file.

    File shape (whitespace-delimited, no header):
         1950    1   -2.3400
         ...

    Returns rows in source order (oldest first) with keys:
      year, month, pna_value
    """
    rows: list[dict] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        parts = s.split()
        if len(parts) != 3:
            continue
        try:
            year = int(parts[0])
            month = int(parts[1])
            val = float(parts[2])
            if not 1 <= month <= 12:
                continue
            rows.append({"year": year, "month": month, "pna_value": val})
        except ValueError:
            continue
    return rows
