"""Shared helpers for the boe_monetary_policy_summary_attribution scenario.

The Bank of England Monetary Policy Committee (MPC) publishes the
'Monetary Policy Summary and Minutes' eight times a year (about every six
weeks). Each release is anchored by the meeting-end date (the Thursday on
which the decision is announced at 12 noon UK time) and labelled by the
publication month — e.g. the meeting ending 20 March 2024 is the
'March 2024' release.

We label each instance with a ``YYYY-MmonthDD`` token (e.g.
``2024-March21``) that round-trips to both the BoE landing-page slug
(``<month>-<YYYY>``) and the PDF slug
(``monetary-policy-summary-and-minutes-<month>-<YYYY>``). Note that the
label does NOT sort lexically by date (April < February alphabetically),
so callers must order by :func:`parse_label` when sequencing instances.
"""
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

# BoE serves HTML and PDFs to browser-like user agents. curl/wget UAs
# return 403; this mirrors what we use for the FOMC scenario.
BOE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.9",
    "Accept-Language": "en-GB,en;q=0.9",
}

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


def month_name(month: int) -> str:
    """Lower-case English month name for the BoE URL slug."""
    return MONTH_NAMES[month - 1]


def label_from_date(d: dt.date) -> str:
    """Canonical label, e.g. ``2024-March20``. Sortable and human-readable."""
    return f"{d.year:04d}-{d.strftime('%B')}{d.day:02d}"


def parse_label(label: str) -> dt.date:
    """Inverse of :func:`label_from_date`."""
    year_part, rest = label.split("-", 1)
    # rest looks like "March20" or "December18"
    month_str = "".join(c for c in rest if c.isalpha())
    day_str = "".join(c for c in rest if c.isdigit())
    month = MONTH_NAMES.index(month_str.lower()) + 1
    return dt.date(int(year_part), month, int(day_str))


def landing_slug(d: dt.date) -> str:
    """BoE landing slug, e.g. 'march-2024'."""
    return f"{month_name(d.month)}-{d.year}"


def pdf_filename(d: dt.date) -> str:
    """Canonical BoE PDF filename for a given meeting (without the .pdf)."""
    return f"monetary-policy-summary-and-minutes-{month_name(d.month)}-{d.year}"


# Canonical MPC meeting dates (final day of the meeting = press date) for
# the 27 meetings in the corpus window. Each row is the Thursday on which
# the decision was announced at 12:00 UK time. Dates verified from the
# BoE public listing pages and contemporary press coverage.
MPC_MEETINGS = [
    "2023-02-02", "2023-03-23", "2023-05-11", "2023-06-22",
    "2023-08-03", "2023-09-21", "2023-11-02", "2023-12-14",
    "2024-02-01", "2024-03-21", "2024-05-09", "2024-06-20",
    "2024-08-01", "2024-09-19", "2024-11-07", "2024-12-19",
    "2025-02-06", "2025-03-20", "2025-05-08", "2025-06-19",
    "2025-08-07", "2025-09-18", "2025-11-06", "2025-12-18",
    "2026-02-05", "2026-03-19", "2026-04-30",
]


def meeting_dates() -> list[dt.date]:
    return [dt.date.fromisoformat(s) for s in MPC_MEETINGS]


def iter_meetings(start_label: str | None = None, end_label: str | None = None):
    """Yield (label, dt.date) for each MPC meeting in [start, end] inclusive.

    If start/end are None, iterate the full canonical list. Bounds compare
    by date (not label) so callers can pass either an ISO date or a label.
    """
    def _to_date(s: str) -> dt.date:
        try:
            return dt.date.fromisoformat(s)
        except ValueError:
            return parse_label(s)

    sd = _to_date(start_label) if start_label else None
    ed = _to_date(end_label)   if end_label   else None
    for d in meeting_dates():
        if sd is not None and d < sd: continue
        if ed is not None and d > ed: continue
        yield label_from_date(d), d
