"""Shared helpers for the IEF Comparative Analysis Hard scenario."""
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

IEF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
}

MONTH_NAMES = ["january","february","march","april","may","june",
               "july","august","september","october","november","december"]

def ief_pdf_url(year: int, month: int) -> str:
    return (f"https://www.ief.org/_resources/files/news/"
            f"comparative-analysis-of-monthly-reports-on-the-oil-market/"
            f"{MONTH_NAMES[month-1]}-{year}/"
            f"ief-comparative-analysis-{month:02d}-{year}.pdf")


def month_label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def parse_label(label: str) -> tuple[int, int]:
    y, m = label.split("-"); return int(y), int(m)


def iter_months(start_label: str, end_label: str):
    y0, m0 = parse_label(start_label); y1, m1 = parse_label(end_label)
    cur = dt.date(y0, m0, 1); stop = dt.date(y1, m1, 1)
    while cur <= stop:
        yield cur.year, cur.month, cur
        cur = dt.date(cur.year + (1 if cur.month == 12 else 0),
                      1 if cur.month == 12 else cur.month + 1, 1)


def last_of_month(year: int, month: int) -> dt.date:
    if month == 12: return dt.date(year + 1, 1, 1) - dt.timedelta(days=1)
    return dt.date(year, month + 1, 1) - dt.timedelta(days=1)
