"""Download the ATA Truck Tonnage Index history from FRED (TRUCKD11).

The FRED CSV download endpoint is:
    https://fred.stlouisfed.org/graph/fredgraph.csv?id=TRUCKD11

The CSV has two columns: DATE (YYYY-MM-DD, first-of-month) and TRUCKD11
(seasonally-adjusted index value). This script writes the CSV verbatim
to timeseries_source/truckd11.csv. `format.py timeseries` reads it and
emits per-instance cumulative CSVs.

Optional: the ATA press-release HTML captures live at
    https://www.trucking.org/news-insights/ata-truck-tonnage-index-<month>-<year>
We do NOT scrape these by default (the GT is fully CSV-derivable). When
operators want richer narrative grounding under gt_source/ they can run
this script with `--with-press-releases` to also pull per-month HTML.

Stage-2 ingestion. Stage-3 transformation lives in `format.py timeseries`.
"""
from __future__ import annotations
import os
import argparse
import sys
import urllib.error
import urllib.request
from datetime import date
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



ROOT = _scenario_data_dir(__file__)
RAW_CSV_DIR = ROOT / "timeseries_source"
GT_DIR = ROOT / "gt_source"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=TRUCKD11"

PRESS_RELEASE_BASE = "https://www.trucking.org/news-insights/ata-truck-tonnage-index"

USER_AGENT = "Mozilla/5.0 (compatible; TimeSage-EV/scaffold)"

MONTH_NAMES = {
    1: "january", 2: "february", 3: "march", 4: "april",
    5: "may", 6: "june", 7: "july", 8: "august",
    9: "september", 10: "october", 11: "november", 12: "december",
}

# Per-instance pull window matches scenario.yaml.
START = date(2024, 5, 1)
END = date(2026, 4, 1)


def fetch_csv(dest: Path) -> bool:
    req = urllib.request.Request(FRED_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"  miss: {FRED_URL} ({exc})", file=sys.stderr)
        return False
    if len(data) < 200:
        print(f"  miss: response too small ({len(data)} bytes)", file=sys.stderr)
        return False
    dest.write_bytes(data)
    return True


def fetch_press_release(y: int, m: int, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 500:
        return True
    url = f"{PRESS_RELEASE_BASE}-{MONTH_NAMES[m]}-{y}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"  miss: {url} ({exc})", file=sys.stderr)
        return False
    if len(html) < 500:
        return False
    dest.write_bytes(html)
    return True


def iter_release_months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            m = 1
            y += 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--with-press-releases", action="store_true",
        help="Also scrape per-month ATA press-release HTML into gt_source/.",
    )
    args = parser.parse_args()

    RAW_CSV_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = RAW_CSV_DIR / "truckd11.csv"
    if fetch_csv(csv_path):
        print(f"wrote {csv_path}")
    else:
        print("FRED CSV fetch failed", file=sys.stderr)
        return 1

    if args.with_press_releases:
        GT_DIR.mkdir(parents=True, exist_ok=True)
        ok = miss = 0
        for y, m in iter_release_months(START, END):
            label = f"{y}-{m:02d}"
            dest = GT_DIR / f"{label}.html"
            if fetch_press_release(y, m, dest):
                ok += 1
            else:
                miss += 1
        print(f"press releases: {ok} ok / {miss} miss")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
