"""Shared helpers for the cdc_us_rsv_positivity_seasonal_phase_weekly Easy scenario.

Easy-tier state identification: read /root/timeseries.csv (CDC NREVSS
weekly RSV percent-positivity at level='National', subtype='Combined Type',
pathogen='RSV', MMWR-week-ending Saturday) and report the latest week's
`rsv_phase` {off_season, active, elevated, peak}.

Classification rule (4-band, vs 5-year same-MMWR-week historical range):
    rsv_phase = 'off_season' if percent_pos <  5yr-pctl-25
              = 'active'     if percent_pos <  5yr-median
              = 'elevated'   if percent_pos <  5yr-pctl-75
              = 'peak'       if percent_pos >= 5yr-pctl-75

The 5-year baseline uses the same MMWR week number from the FIVE
years immediately preceding the target year (e.g., for 2025-W48 the
baseline is built from 2020-W48..2024-W48 same-week values). The
percentiles are computed with `statistics.quantiles(method='exclusive')`.

This is a fixed deterministic rule because the historical reference
window is fully encoded in the cumulative time-series CSV — the CSV
ships ~6 years of weekly history covering 2019-07 onward, so the
agent can recompute the 5-yr same-week distribution itself.
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

# CDC NREVSS percent-positivity (Socrata id rgnm-fkqb). Public, no API key.
CDC_API_URL = (
    "https://data.cdc.gov/resource/rgnm-fkqb.csv"
    "?$select=mmwrweek_end,percent_pos"
    "&pathogen=RSV"
    "&level=National"
    "&subtype=Combined%20Type"
    "&$order=mmwrweek_end%20ASC"
    "&$limit=2000"
)
DATASET_ID = "rgnm-fkqb"
DATASET_NAME = ("Percent positivity of respiratory viruses by nucleic acid "
                "amplification tests (NAATs), NREVSS Dashboard")
PAGE_URL = ("https://data.cdc.gov/Public-Health-Surveillance/"
            "Percent-positivity-of-respiratory-viruses-by-nucle/rgnm-fkqb")
PATHOGEN = "RSV"
UNIT = "percent positive"

# 4-state vocabulary, ordered from low to peak.
CATEGORIES = ["off_season", "active", "elevated", "peak"]

# Number of years for the same-week historical baseline.
BASELINE_YEARS = 5


def _quartiles(vals: list[float]) -> tuple[float, float, float]:
    """Return (p25, p50, p75) over a list of floats using exclusive quantiles
    (which matches `statistics.quantiles(n=4)` defaults)."""
    if len(vals) < 3:
        raise ValueError(f"need >=3 values for quartiles, got {len(vals)}")
    qs = statistics.quantiles(vals, n=4)
    return qs[0], qs[1], qs[2]


def classify(percent_pos: float,
             same_week_baseline: list[float]) -> str:
    """Map (current value, 5-yr same-week list) to a categorical phase."""
    if percent_pos is None:
        return None
    if len(same_week_baseline) < 3:
        raise ValueError(
            f"insufficient baseline for percentile rule: need >=3, "
            f"got {len(same_week_baseline)}"
        )
    p25, p50, p75 = _quartiles(same_week_baseline)
    if percent_pos < p25: return "off_season"
    if percent_pos < p50: return "active"
    if percent_pos < p75: return "elevated"
    return "peak"


def week_label(saturday: dt.date) -> str:
    """Return ISO-week label `YYYY-Www` for a Saturday MMWR-week-ending."""
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


def same_week_baseline(history_rows: list[dict],
                       target_iso_week: int,
                       target_year: int,
                       n_years: int = BASELINE_YEARS) -> list[float]:
    """Return the list of percent_pos values for the same MMWR week number
    in the `n_years` years immediately preceding `target_year`.

    `history_rows` is a list of dicts with keys 'week_ending' (YYYY-MM-DD)
    and 'percent_pos' (float-able). Rows from the target year (or later)
    are excluded.
    """
    out: list[float] = []
    for r in history_rows:
        d = dt.date.fromisoformat(r["week_ending"])
        iso = d.isocalendar()
        if iso.year >= target_year:
            continue
        if iso.year < target_year - n_years:
            continue
        if iso.week != target_iso_week:
            continue
        try:
            out.append(float(r["percent_pos"]))
        except (TypeError, ValueError):
            continue
    return out


def period_long(year: int, week: int) -> str:
    return f"ISO week {year:04d}-W{week:02d}"
