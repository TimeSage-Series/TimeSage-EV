"""Shared helpers for portla_monthly_cargo_stats_brief."""
from __future__ import annotations
import os
import datetime as dt
import re
import time
import urllib.request
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

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

# Per-year historical-TEU pages — they contain the cumulative monthly table.
YEARS = [2024, 2025, 2026]
URL_TEMPLATE = (
    "https://portoflosangeles.org/business/statistics/"
    "container-statistics/historical-teu-statistics-{year}"
)

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]

# 24-month window: 2024-04 → 2026-03 (April 2026 data typically published mid-May)
REPORT_MONTHS = []
y, m = 2024, 4
for _ in range(24):
    REPORT_MONTHS.append((y, m))
    m += 1
    if m == 13:
        m = 1; y += 1


def http_get(url: str, dest: Path, sleep_s: float = 1.5) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
    dest.write_bytes(body)
    time.sleep(sleep_s)


def parse_historical_page(html: str, year: int) -> dict:
    """Parse a Port-of-LA historical-TEU page for a year. Returns
    {YYYY-MM: {loaded_imports, total_imports, loaded_exports, total_exports,
               total_teus, yoy_pct}}.
    """
    clean = re.sub(r"<[^>]+>", " ", html)
    clean = re.sub(r"&nbsp;|&#xA0;", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    out: dict = {}
    # Pattern: "<Month> <loaded_imp> <empty_imp> <total_imp> <loaded_exp>
    #          <empty_exp> <total_exp> <total_teus> <yoy_pct>%"
    # All numbers may have commas + decimals.
    num = r"[\d,]+(?:\.\d+)?"
    for month_idx, month in enumerate(MONTH_NAMES, start=1):
        # Allow whitespace + numbers, ending in a yoy percent
        pat = (rf"{month}\s+({num})\s+({num})\s+({num})\s+({num})\s+"
               rf"({num})\s+({num})\s+({num})\s+(-?[\d\.]+)%")
        m = re.search(pat, clean)
        if m:
            try:
                row = {
                    "loaded_imports": float(m.group(1).replace(",", "")),
                    "empty_imports": float(m.group(2).replace(",", "")),
                    "total_imports": float(m.group(3).replace(",", "")),
                    "loaded_exports": float(m.group(4).replace(",", "")),
                    "empty_exports": float(m.group(5).replace(",", "")),
                    "total_exports": float(m.group(6).replace(",", "")),
                    "total_teus": float(m.group(7).replace(",", "")),
                    "yoy_pct": float(m.group(8)),
                }
                out[f"{year}-{month_idx:02d}"] = row
            except (ValueError, IndexError):
                continue
    return out
