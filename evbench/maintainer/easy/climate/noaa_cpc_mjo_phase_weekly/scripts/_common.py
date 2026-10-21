"""Shared helpers for the noaa_cpc_mjo_phase_weekly scenario.

The Madden-Julian Oscillation (MJO) is a 30-60 day eastward-propagating
mode of tropical convection-circulation coupling. NOAA PSL publishes a
real-time OLR-based MJO Index (ROMI) daily. ROMI is delivered in
PC1/PC2 form with reversed sign and swapped order relative to the
canonical Wheeler-Hendon RMM convention. Per PSL guidance:

    RMM1 = ROMI_PC2
    RMM2 = -ROMI_PC1

The pipeline materialises rmm1/rmm2/amplitude/derived_phase columns
directly in the per-instance CSV.
"""
from __future__ import annotations
import os
import datetime as dt
import math
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

ROMI_TXT_URL = (
    "https://www.psl.noaa.gov/mjo/mjoindex/romi.cpcolr.1x.txt"
)
MJO_DASHBOARD_URL = "https://www.psl.noaa.gov/mjo/"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/plain,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

MJO_PHASE_OPTIONS = [
    "weak", "phase_1", "phase_2", "phase_3", "phase_4",
    "phase_5", "phase_6", "phase_7", "phase_8",
]
WEAK_AMPLITUDE = 1.0


def classify_phase(rmm1: float, rmm2: float) -> tuple[float, str]:
    """Return (amplitude, phase_label) per the Wheeler-Hendon convention."""
    amp = math.sqrt(rmm1 * rmm1 + rmm2 * rmm2)
    if amp < WEAK_AMPLITUDE:
        return amp, "weak"
    # 8-sector phase wheel. Standard Wheeler & Hendon (2004) numbering:
    #   phase 1: RMM1<0, RMM2<0, |RMM1|>=|RMM2|  (Western Hemisphere/Africa)
    #   phase 2: RMM1<0, RMM2<0, |RMM1|< |RMM2|  (W.Hem/Africa -> Indian Ocean)
    #   phase 3: RMM1>0, RMM2<0, RMM1   < |RMM2| (Indian Ocean)
    #   phase 4: RMM1>0, RMM2<0, RMM1   >=|RMM2| (Indian Ocean -> Maritime)
    #   phase 5: RMM1>0, RMM2>0, RMM1   > RMM2   (Maritime Continent)
    #   phase 6: RMM1>0, RMM2>0, RMM1   <=RMM2   (Maritime -> W.Pacific)
    #   phase 7: RMM1<0, RMM2>0, |RMM1| <=RMM2   (Western Pacific)
    #   phase 8: RMM1<0, RMM2>0, |RMM1| > RMM2   (W.Pacific -> W.Hem)
    if rmm1 < 0 and rmm2 < 0:
        if abs(rmm1) >= abs(rmm2):
            return amp, "phase_1"
        else:
            return amp, "phase_2"
    if rmm1 > 0 and rmm2 < 0:
        if rmm1 < abs(rmm2):
            return amp, "phase_3"
        else:
            return amp, "phase_4"
    if rmm1 > 0 and rmm2 > 0:
        if rmm1 > rmm2:
            return amp, "phase_5"
        else:
            return amp, "phase_6"
    if rmm1 < 0 and rmm2 > 0:
        if abs(rmm1) <= rmm2:
            return amp, "phase_7"
        else:
            return amp, "phase_8"
    # Degenerate (axis cases) -> nearest sector by convention.
    return amp, "phase_1"


def week_label(d: dt.date) -> str:
    iso = d.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def friday_of_iso_week(year: int, week: int) -> dt.date:
    return dt.date.fromisocalendar(year, week, 5)


def iter_weeks(start_label: str, end_label: str):
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


def parse_romi_ascii(text: str) -> dict[dt.date, tuple[float, float]]:
    """Parse the PSL ROMI ascii file. Returns a dict mapping
    date -> (rmm1, rmm2) per the PSL sign/order convention.

    File shape (whitespace-delimited, no header):

        1991  1  1  0     0.12526    -0.06945     0.14323
        ^year ^m ^d ^?    ^ROMI_PC1  ^ROMI_PC2    ^amplitude

    PSL convention: RMM1 = ROMI_PC2, RMM2 = -ROMI_PC1.
    """
    out: dict[dt.date, tuple[float, float]] = {}
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        parts = s.split()
        if len(parts) < 7:
            continue
        try:
            year = int(parts[0]); month = int(parts[1]); day = int(parts[2])
            pc1 = float(parts[4])
            pc2 = float(parts[5])
            if not (1700 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
                continue
            d = dt.date(year, month, day)
            rmm1 = pc2
            rmm2 = -pc1
            out[d] = (rmm1, rmm2)
        except (ValueError, IndexError):
            continue
    return out
