"""Ingest 24 historical BEA Personal Income & Outlays monthly release pages
into gt_source/ as HTML. Each page carries BEA's official narrative
commentary on PCE inflation (headline + core) plus the supporting tables.

Source: https://www.bea.gov/news/<release-year>/personal-income-and-outlays-<data-month>-<data-year>

Pattern wrinkles:
- Dec 2024 data was released in Jan 2025, so it lives under /news/2025/.
- BEA released a joint Oct+Nov 2025 page in 2026.

Saves each HTML as gt_source/<data-month>.html.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

MONTH_NAMES = {
    "01": "january", "02": "february", "03": "march", "04": "april",
    "05": "may", "06": "june", "07": "july", "08": "august",
    "09": "september", "10": "october", "11": "november", "12": "december",
}

# (data_month, release_year, url_slug). Release year is the year the
# release page was published — usually equals data year, but Dec data lands
# in the following Jan, and the gov-shutdown joint release goes to 2026.
RELEASES = [
    ("2024-04", 2024, "personal-income-and-outlays-april-2024"),
    ("2024-05", 2024, "personal-income-and-outlays-may-2024"),
    ("2024-06", 2024, "personal-income-and-outlays-june-2024"),
    ("2024-07", 2024, "personal-income-and-outlays-july-2024"),
    ("2024-08", 2024, "personal-income-and-outlays-august-2024"),
    ("2024-09", 2024, "personal-income-and-outlays-september-2024"),
    ("2024-10", 2024, "personal-income-and-outlays-october-2024"),
    ("2024-11", 2024, "personal-income-and-outlays-november-2024"),
    ("2024-12", 2025, "personal-income-and-outlays-december-2024"),
    ("2025-01", 2025, "personal-income-and-outlays-january-2025"),
    ("2025-02", 2025, "personal-income-and-outlays-february-2025"),
    ("2025-03", 2025, "personal-income-and-outlays-march-2025"),
    ("2025-04", 2025, "personal-income-and-outlays-april-2025"),
    ("2025-05", 2025, "personal-income-and-outlays-may-2025"),
    ("2025-06", 2025, "personal-income-and-outlays-june-2025"),
    ("2025-07", 2025, "personal-income-and-outlays-july-2025"),
    ("2025-08", 2025, "personal-income-and-outlays-august-2025"),
    ("2025-09", 2025, "personal-income-and-outlays-september-2025"),
    # Oct+Nov 2025 ran as a single joint release in 2026 post-shutdown.
    ("2025-10", 2026, "personal-income-and-outlays-october-and-november-2025"),
    ("2025-11", 2026, "personal-income-and-outlays-october-and-november-2025"),
    ("2025-12", 2026, "personal-income-and-outlays-december-2025"),
    ("2026-01", 2026, "personal-income-and-outlays-january-2026"),
    ("2026-02", 2026, "personal-income-and-outlays-february-2026"),
    ("2026-03", 2026, "personal-income-and-outlays-march-2026"),
]


def fetch_one(data_month: str, release_year: int, slug: str) -> bool:
    url = f"https://www.bea.gov/news/{release_year}/{slug}"
    dst = GT_SOURCE / f"{data_month}.html"
    if dst.exists() and dst.stat().st_size > 20_000:
        print(f"  {data_month} -> cached ({dst.stat().st_size} bytes)", file=sys.stderr)
        return True
    req = Request(url, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=60) as r:
            blob = r.read()
    except Exception as exc:  # noqa: BLE001
        print(f"  {data_month} -> FAIL: {exc}", file=sys.stderr)
        return False
    if len(blob) < 5_000:
        print(f"  {data_month} -> bad payload ({len(blob)} bytes)", file=sys.stderr)
        return False
    dst.write_bytes(blob)
    print(f"  {data_month} -> {len(blob)} bytes", file=sys.stderr)
    return True


def main() -> int:
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    ok = 0
    for dmonth, ryear, slug in RELEASES:
        if fetch_one(dmonth, ryear, slug):
            ok += 1
        time.sleep(0.3)
    print(f"fetched {ok}/{len(RELEASES)} BEA pages", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
