"""Shared helpers for the eia_wpsr_weekly_petroleum_brief scenario."""
from __future__ import annotations
import datetime as dt
import os
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

# EIA API key — loaded from env, with v0 .env as a fallback for local use.
def eia_api_key() -> str | None:
    key = os.environ.get("EIA_API_KEY")
    if key: return key
    v0 = Path(__file__).resolve().parents[6] / "scenarios_v0/energy/.env"
    if v0.exists():
        for line in v0.read_text().splitlines():
            if line.startswith("EIA_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


# Browser-like UA — EIA serves PDFs to scriptable UAs but some Akamai paths
# are sensitive.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept": "*/*",
}

# WPSR release timing: Wednesday weekly (data), Thursday (highlights).
def recent_wednesdays(n: int, anchor: dt.date | None = None) -> list[dt.date]:
    if anchor is None:
        anchor = dt.date.today()
    # Wednesday weekday=2
    delta = (anchor.weekday() - 2) % 7
    last_wed = anchor - dt.timedelta(days=delta)
    out = [last_wed - dt.timedelta(days=7 * i) for i in range(n)]
    out.reverse()
    return out


def wed_label(d: dt.date) -> str:
    """ISO date string of the Wednesday."""
    return d.isoformat()


def parse_label(label: str) -> dt.date:
    return dt.date.fromisoformat(label)


def iter_weeks(start: dt.date, end: dt.date):
    cur = start
    while cur <= end:
        yield cur
        cur += dt.timedelta(days=7)
