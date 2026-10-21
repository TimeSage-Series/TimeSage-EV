"""Shared helpers for eia_monthly_energy_review_analytical."""
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
    "Accept": "*/*",
}


def iter_months(start_label: str, end_label: str):
    """Yield datetime.date(YYYY, MM, 1) inclusive."""
    sy, sm = (int(x) for x in start_label.split("-"))
    ey, em = (int(x) for x in end_label.split("-"))
    cur = dt.date(sy, sm, 1)
    stop = dt.date(ey, em, 1)
    while cur <= stop:
        yield cur
        if cur.month == 12:
            cur = dt.date(cur.year + 1, 1, 1)
        else:
            cur = dt.date(cur.year, cur.month + 1, 1)


def month_label(d: dt.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def shift_month(label: str, delta: int) -> str:
    """Shift YYYY-MM by delta months (positive = forward, negative = backward)."""
    y, m = (int(x) for x in label.split("-"))
    idx = y * 12 + (m - 1) + delta
    ny = idx // 12
    nm = (idx % 12) + 1
    return f"{ny:04d}-{nm:02d}"


def data_month_for(release_label: str) -> str:
    """EIA MER release at YYYY-MM has data through (YYYY-MM - 2)."""
    return shift_month(release_label, -2)


def mer_archive_pdf_filename(release_label: str) -> str:
    """EIA archive naming: 00352YMM.pdf -- two-digit year + two-digit month."""
    y, m = (int(x) for x in release_label.split("-"))
    return f"003525{m:02d}.pdf" if y == 2025 else (
        f"003524{m:02d}.pdf" if y == 2024 else (
            f"003526{m:02d}.pdf" if y == 2026 else None
        )
    )


def mer_archive_pdf_url(release_label: str) -> str:
    fn = mer_archive_pdf_filename(release_label)
    if not fn:
        raise ValueError(f"no archive naming pattern for {release_label}")
    return f"https://www.eia.gov/totalenergy/data/monthly/archive/{fn}"


MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def long_month_label(label: str) -> str:
    y, m = (int(x) for x in label.split("-"))
    return f"{MONTH_NAMES[m - 1]} {y}"
