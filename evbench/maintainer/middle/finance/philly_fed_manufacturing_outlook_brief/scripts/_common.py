"""Shared helpers for philly_fed_manufacturing_outlook_brief.

Philadelphia Fed Manufacturing Business Outlook Survey (MBOS) is a monthly
diffusion-index report published on the third Thursday of each month at a
deterministic URL:

    https://www.philadelphiafed.org/-/media/frbp/assets/surveys-and-data/
    mbos/<YYYY>/bos<MM><YY>.pdf

where <YY> is the 2-digit year. 28 consecutive months 2024-01..2026-04 all
verified HTTP 200 at build time -- the URL pattern is reliably complete
(no publication gaps).

The PDF carries a narrative summary on pages 1-2 followed by tabular
diffusion indexes (general activity / new orders / shipments / employment /
prices paid). We extract the headline numerics + a verbatim summary block.
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

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/pdf,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}


def pdf_url_for(year: int, month: int) -> str:
    yy = year % 100
    return (
        f"https://www.philadelphiafed.org/-/media/frbp/assets/surveys-and-data/"
        f"mbos/{year:04d}/bos{month:02d}{yy:02d}.pdf"
    )


def month_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def month_label_long(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year:04d}"


def iter_months(start_label: str, end_label: str):
    y0, m0 = int(start_label[:4]), int(start_label[5:7])
    y1, m1 = int(end_label[:4]),   int(end_label[5:7])
    while (y0, m0) <= (y1, m1):
        yield y0, m0
        m0 += 1
        if m0 > 12:
            m0 = 1; y0 += 1
