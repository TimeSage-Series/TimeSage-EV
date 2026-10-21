"""Shared helpers for ecb_monetary_policy_statement_attribution.

The ECB Governing Council holds eight monetary-policy meetings per year
(~every six weeks). Each meeting day, the Governing Council publishes a
'Combined monetary policy decisions and statement' PDF and a 'Monetary
policy statement (with Q&A)' HTML landing page.

Each meeting is one instance. The canonical label is YYYY-MmonthDD, where
'month' is the lowercase three-letter month name capitalized to title case
(e.g. 2026-Mar06). This labelling sorts chronologically inside the corpus
and is human-readable.
"""
from __future__ import annotations
import os
import calendar
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

# The ECB requires a browser-style UA header; default urllib UA returns 403.
ECB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}


def label_from_date(d: dt.date) -> str:
    """Canonical meeting label: e.g. 2026-Mar06.

    Format: YYYY-MmonNN where 'mon' is the title-cased three-letter month
    abbreviation and NN is the zero-padded day. Sorts chronologically
    inside each year and reads naturally for a finance audience.
    """
    mon = calendar.month_abbr[d.month]  # 'Jan', 'Feb', ...
    return f"{d.year:04d}-{mon}{d.day:02d}"


def parse_label(label: str) -> dt.date:
    """Inverse of label_from_date — '2026-Mar06' -> date(2026, 3, 6)."""
    year_str, mon_day = label.split("-", 1)
    mon = mon_day[:3]
    day = int(mon_day[3:])
    month = list(calendar.month_abbr).index(mon)
    return dt.date(int(year_str), month, day)


def in_range(d: dt.date, start: dt.date, end: dt.date) -> bool:
    return start <= d <= end


def iter_meetings(meetings: list[str], start_label: str | None, end_label: str | None):
    """Yield meeting date objects within the inclusive [start, end] label window.

    `meetings` is the canonical list of ISO meeting dates (YYYY-MM-DD). If
    start_label or end_label is None, the corresponding bound is unbounded.
    """
    start = parse_label(start_label) if start_label else dt.date.min
    end = parse_label(end_label) if end_label else dt.date.max
    for iso in meetings:
        d = dt.date.fromisoformat(iso)
        if start <= d <= end:
            yield d
