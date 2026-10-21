"""Shared helpers for usda_crop_progress_weekly_brief."""
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


def nass_api_key() -> str | None:
    key = os.environ.get("NASS_API_KEY")
    if key: return key
    v0 = Path(__file__).resolve().parents[6] / "scenarios_v0/agriculture/.env"
    if v0.exists():
        for line in v0.read_text().splitlines():
            if line.startswith("NASS_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept": "*/*",
}


def usda_week_label(year: int, week: int) -> str:
    return f"{year:04d}-wk{week:02d}"


def parse_label(label: str) -> tuple[int, int]:
    y, w = label.split("-wk")
    return int(y), int(w)


def usda_week_monday(year: int, week: int) -> dt.date:
    """USDA reporting week numbering: week 1 starts the first Monday of the
    year-of-reporting. Approximation: align with ISO week (close enough for
    growing-season tracking)."""
    jan4 = dt.date(year, 1, 4)
    monday_w1 = jan4 - dt.timedelta(days=jan4.isoweekday() - 1)
    return monday_w1 + dt.timedelta(days=(week - 1) * 7)
