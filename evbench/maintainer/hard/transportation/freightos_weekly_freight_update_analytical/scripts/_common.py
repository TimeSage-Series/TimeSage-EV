"""Shared helpers for freightos_weekly_freight_update_analytical."""
from __future__ import annotations
import os
import datetime as dt
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
TS_SOURCE = SCENARIO_ROOT / "timeseries_source"
GT_SOURCE = SCENARIO_ROOT / "gt_source"
INSTANCES = SCENARIO_ROOT / "instances"
ENV = SCENARIO_ROOT / "environment"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

INDEX_URL = "https://www.freightos.com/freight-industry-updates/weekly-freight-updates/"

MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_date_from_slug(slug: str):
    """Extract a publication date from a Freightos update slug.

    Slugs look like:
      asia-europe-container-rates-slide-transpac-more-buoyant-may-5-2026-update
      freight-rates-elevated-but-mostly-level-as-war-stretches-on-april-07-2026-update
      lny-demand-pushing-ocean-rates-up-as-air-moves-past-peak-january-6-2026-update

    The date is always at the tail just before '-update', as
    '<month>-<day>-<year>' (day may be 1- or 2-digit, zero-padded or not).
    """
    s = slug.rstrip("/")
    if s.endswith("-update"):
        s = s[: -len("-update")]
    parts = s.rsplit("-", 3)
    if len(parts) < 4:
        return None
    month_word, day_word, year_word = parts[-3], parts[-2], parts[-1]
    if month_word not in MONTH_NAMES:
        return None
    try:
        return dt.date(int(year_word), MONTH_NAMES[month_word], int(day_word))
    except (ValueError, KeyError):
        return None


def html_filename(d: dt.date) -> str:
    return f"freightos_{d.isoformat()}.html"
