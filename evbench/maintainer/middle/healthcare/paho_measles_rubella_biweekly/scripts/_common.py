"""Shared helpers for the paho_measles_rubella_biweekly scenario scripts.

PAHO publishes its Measles-Rubella bulletin on a bi-weekly cadence: each
issue covers TWO consecutive ISO weeks (e.g., "15-16" covers ISO weeks 15
and 16 of 2026). Issue labels are of the form ``YYYY-Www1-w2`` where
``w1`` and ``w2`` are zero-padded two-digit ISO week numbers (e.g.
``2026-W15-16``, ``2025-W01-02``). Cumulative ordering is anchored to
the Saturday of the LATTER week (w2) of each issue.
"""
from __future__ import annotations
import os
import datetime as dt
import re
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


# --- ISO-week helpers ---

def iso_saturday(year: int, week: int) -> dt.date:
    """Return the Saturday of the given ISO year/week (ISO 8601, Mon-Sun)."""
    monday = dt.date.fromisocalendar(year, week, 1)
    return monday + dt.timedelta(days=5)


# --- Bi-weekly label helpers ---

LABEL_RE = re.compile(r"^(\d{4})-W(\d{2})-(\d{2})$")


def biweekly_label(year: int, w1: int, w2: int) -> str:
    """Build canonical issue label, e.g. (2026, 15, 16) -> '2026-W15-16'."""
    return f"{year:04d}-W{w1:02d}-{w2:02d}"


def parse_biweekly_label(label: str) -> tuple[int, int, int]:
    """Parse 'YYYY-Www1-w2' -> (year, w1, w2). Raises on bad input."""
    m = LABEL_RE.match(label)
    if not m:
        raise ValueError(f"Bad bi-weekly label: {label!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def paho_saturday(year: int, w2: int) -> dt.date:
    """Saturday of the LATTER week of a bi-weekly issue (used for ordering)."""
    return iso_saturday(year, w2)


def _iter_iso_weeks(start_year: int, start_week: int,
                    end_year: int, end_week: int):
    """Yield (year, week) tuples inclusive from start to end."""
    cur = dt.date.fromisocalendar(start_year, start_week, 1)
    stop = dt.date.fromisocalendar(end_year, end_week, 1)
    while cur <= stop:
        iso = cur.isocalendar()
        yield iso.year, iso.week
        cur += dt.timedelta(days=7)


def iter_biweekly_issues(start_label: str, end_label: str):
    """Yield (year, w1, w2, saturday_of_w2) tuples inclusive from start to end.

    The walk steps two ISO weeks at a time, anchored to the START label.
    Stops once the latter week (w2) would exceed the end label's w2.
    """
    sy, sw1, _sw2 = parse_biweekly_label(start_label)
    ey, _ew1, ew2 = parse_biweekly_label(end_label)
    # Walk in 2-week strides via Monday-of-w1 dates.
    cur = dt.date.fromisocalendar(sy, sw1, 1)
    # Stop = Monday-of-ew2's week
    stop = dt.date.fromisocalendar(ey, ew2, 1)
    while cur <= stop:
        iso_w1 = cur.isocalendar()
        nxt = cur + dt.timedelta(days=7)
        iso_w2 = nxt.isocalendar()
        # Both weeks must share the same ISO year for a clean label; if
        # they cross an ISO-year boundary we still use the year of w1.
        yield iso_w1.year, iso_w1.week, iso_w2.week, iso_saturday(iso_w2.year, iso_w2.week)
        cur += dt.timedelta(days=14)


# PAHO landing pages accept a normal browser UA without any other
# exotic headers; no Cloudflare / bot check.
PAHO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
}
