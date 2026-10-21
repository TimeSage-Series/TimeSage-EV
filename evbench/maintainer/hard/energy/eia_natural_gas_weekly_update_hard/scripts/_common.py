"""Shared helpers for eia_natural_gas_weekly_update_hard.

The EIA Natural Gas Weekly Update (NGW) is a weekly HTML report published
on Thursdays covering Henry Hub spot/futures prices, regional spot prices
with weather attribution, LNG cargoes, storage, and supply/demand
commentary -- a textbook Hard-tier analytical brief.

URL pattern:
    https://www.eia.gov/naturalgas/weekly/archivenew_ngwu/<YYYY>/<MM>_<DD>/

where <MM>_<DD> is the publication-Thursday date. Some Thursdays are
skipped (Thanksgiving, Christmas, New Year, sporadic operational gaps);
`download.py gt` drives off an explicit per-instance URL list and tolerates
HEAD-404.

We label each issue by its publication-Thursday date in the canonical
YYYY-MM-DD form. The instance window is built from the most recent N
verified-publication Thursdays.
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

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

NGW_BASE = "https://www.eia.gov/naturalgas/weekly/archivenew_ngwu"


def url_for(date_iso: str) -> str:
    d = dt.date.fromisoformat(date_iso)
    return f"{NGW_BASE}/{d.year:04d}/{d.month:02d}_{d.day:02d}/"


def next_thursday_after(date_iso: str) -> str:
    d = dt.date.fromisoformat(date_iso) + dt.timedelta(days=7)
    return d.isoformat()
