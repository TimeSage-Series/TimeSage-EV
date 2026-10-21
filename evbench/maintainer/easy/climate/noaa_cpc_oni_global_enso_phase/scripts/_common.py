"""Shared helpers for the noaa_cpc_oni_global_enso_phase scenario."""
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

# ONI ascii file lives at a single canonical URL maintained by NOAA CPC.
# Updated by ~5th of each month for the most recently completed 3-month
# overlapping season.
ONI_TXT_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"

# Companion HTML dashboard (the page that renders ONI as a colored table).
# We snapshot it once as gt_source evidence for V4 traceability — the
# dashboard is the human-readable companion that the categorical labels
# are derived against.
ONI_DASHBOARD_URL = (
    "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php"
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

# ONI 3-month overlapping season codes, in calendar order. The "year" of
# a season is the year of its centered month (DJF YYYY = Dec(YYYY-1), Jan
# YYYY, Feb YYYY → centered on Jan YYYY → year = YYYY).
SEASON_CODES = [
    "DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ",
    "JJA", "JAS", "ASO", "SON", "OND", "NDJ",
]
# centered month per season code (1=Jan … 12=Dec)
SEASON_CENTERED_MONTH = {
    "DJF":  1, "JFM":  2, "FMA":  3, "MAM":  4, "AMJ":  5, "MJJ":  6,
    "JJA":  7, "JAS":  8, "ASO":  9, "SON": 10, "OND": 11, "NDJ": 12,
}

# Operational categorical thresholds per the CPC ENSO definition page:
# warm conditions when ONI anomaly ≥ +0.5 °C; cool when ≤ -0.5 °C; else
# ENSO-Neutral. This is the per-season categorization used to color
# cells red / blue / white on the ONI dashboard. See
# environment/question_template.md for the rule the agent applies.
WARM_THRESHOLD = 0.5
COOL_THRESHOLD = -0.5

ENSO_PHASE_OPTIONS = ["El Nino", "La Nina", "ENSO-Neutral"]


def season_centered_date(season_code: str, year: int) -> dt.date:
    """Return a date object pegged to the 15th of the centered month.

    This is the canonical "publish anchor" we use to order instance
    folders. e.g. FMA 2026 → 2026-03-15 → folder `2026-03`.
    """
    month = SEASON_CENTERED_MONTH[season_code]
    return dt.date(year, month, 15)


def season_to_folder(season_code: str, year: int) -> str:
    """Folder name for the per-period instance directory.

    Convention: YYYY-MM where MM is the centered month of the season.
    e.g. FMA 2026 → "2026-03".
    """
    month = SEASON_CENTERED_MONTH[season_code]
    return f"{year:04d}-{month:02d}"


def season_label(season_code: str, year: int) -> str:
    """Human-readable label as NOAA writes it: 'FMA 2026'."""
    return f"{season_code} {year:04d}"


def classify_phase(anomaly_c: float) -> str:
    """Apply the per-season ONI threshold rule.

    Returns one of ENSO_PHASE_OPTIONS.
    """
    if anomaly_c >= WARM_THRESHOLD:
        return "El Nino"
    if anomaly_c <= COOL_THRESHOLD:
        return "La Nina"
    return "ENSO-Neutral"


def parse_oni_ascii(text: str) -> list[dict]:
    """Parse the ONI ascii.txt content into a list of row dicts.

    File shape:
         SEAS  YR   TOTAL   ANOM
          DJF 1950  24.72  -1.53
          JFM 1950  25.17  -1.34
          ...

    Returns rows in source order (oldest first) with keys:
      season, year, total_sst_c, anomaly_c
    """
    rows: list[dict] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("SEAS"):
            continue
        parts = s.split()
        if len(parts) != 4:
            continue
        season, year_s, total_s, anom_s = parts
        if season not in SEASON_CENTERED_MONTH:
            continue
        try:
            rows.append({
                "season": season,
                "year": int(year_s),
                "total_sst_c": float(total_s),
                "anomaly_c": float(anom_s),
            })
        except ValueError:
            continue
    return rows
