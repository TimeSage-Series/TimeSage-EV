"""Ingest 24 weekly CDC FluView surveillance reports into gt_source/. FluView
is CDC's weekly publication for U.S. respiratory-virus hospitalization
surveillance, covering FluSurv-NET (flu hospitalization) directly and
cross-referencing COVID-NET, RSV-NET, and the RESP-NET umbrella in its
text. It is the closest weekly narrative bulletin CDC publishes that
maps onto this scenario's instance window.

URL patterns differ between 2023-24 season (old `flu/weekly/...` paths)
and 2024-25+ (current `fluview/surveillance/...` paths). Both are mapped
explicitly below.

Saves each HTML as gt_source/<week-ending-Saturday>.html.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

# (week_ending_saturday, mmwr_year, mmwr_week, url)
RELEASES = [
    ("2024-04-06", 2024, 14, "https://www.cdc.gov/flu/weekly/weeklyarchives2023-2024/Week14.htm"),
    ("2024-05-04", 2024, 18, "https://www.cdc.gov/flu/weekly/weeklyarchives2023-2024/Week18.htm"),
    ("2024-05-25", 2024, 21, "https://www.cdc.gov/flu/weekly/weeklyarchives2023-2024/Week21.htm"),
    ("2024-06-22", 2024, 25, "https://www.cdc.gov/flu/weekly/weeklyarchives2023-2024/Week25.htm"),
    ("2024-07-20", 2024, 29, "https://www.cdc.gov/flu/weekly/weeklyarchives2023-2024/Week29.htm"),
    ("2024-08-17", 2024, 33, "https://www.cdc.gov/flu/weekly/weeklyarchives2023-2024/Week33.htm"),
    ("2024-09-07", 2024, 36, "https://www.cdc.gov/fluview/surveillance/2024-week-36.html"),
    ("2024-10-05", 2024, 40, "https://www.cdc.gov/fluview/surveillance/2024-week-40.html"),
    ("2024-11-02", 2024, 44, "https://www.cdc.gov/fluview/surveillance/2024-week-44.html"),
    ("2024-11-30", 2024, 48, "https://www.cdc.gov/fluview/surveillance/2024-week-48.html"),
    ("2024-12-21", 2024, 51, "https://www.cdc.gov/fluview/surveillance/2024-week-51.html"),
    ("2025-01-18", 2025, 3,  "https://www.cdc.gov/fluview/surveillance/2025-week-03.html"),
    ("2025-02-15", 2025, 7,  "https://www.cdc.gov/fluview/surveillance/2025-week-07.html"),
    ("2025-03-15", 2025, 11, "https://www.cdc.gov/fluview/surveillance/2025-week-11.html"),
    ("2025-04-05", 2025, 14, "https://www.cdc.gov/fluview/surveillance/2025-week-14.html"),
    ("2025-05-03", 2025, 18, "https://www.cdc.gov/fluview/surveillance/2025-week-18.html"),
    ("2025-10-25", 2025, 43, "https://www.cdc.gov/fluview/surveillance/2025-week-43.html"),
    ("2025-11-22", 2025, 47, "https://www.cdc.gov/fluview/surveillance/2025-week-47.html"),
    ("2025-12-13", 2025, 50, "https://www.cdc.gov/fluview/surveillance/2025-week-50.html"),
    ("2026-01-10", 2026, 1,  "https://www.cdc.gov/fluview/surveillance/2026-week-01.html"),
    ("2026-02-07", 2026, 5,  "https://www.cdc.gov/fluview/surveillance/2026-week-05.html"),
    ("2026-03-07", 2026, 9,  "https://www.cdc.gov/fluview/surveillance/2026-week-09.html"),
    ("2026-03-28", 2026, 12, "https://www.cdc.gov/fluview/surveillance/2026-week-12.html"),
    ("2026-04-25", 2026, 16, "https://www.cdc.gov/fluview/surveillance/2026-week-16.html"),
]


def fetch_one(week_ending: str, url: str) -> bool:
    dst = GT_SOURCE / f"{week_ending}.html"
    if dst.exists() and dst.stat().st_size > 20_000:
        print(f"  {week_ending} -> cached ({dst.stat().st_size} bytes)", file=sys.stderr)
        return True
    req = Request(url, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=60) as r:
            blob = r.read()
    except Exception as exc:  # noqa: BLE001
        print(f"  {week_ending} -> FAIL: {exc}", file=sys.stderr)
        return False
    if len(blob) < 10_000:
        print(f"  {week_ending} -> small payload ({len(blob)} bytes)", file=sys.stderr)
        return False
    dst.write_bytes(blob)
    print(f"  {week_ending} -> {len(blob)} bytes", file=sys.stderr)
    return True


def main() -> int:
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    ok = 0
    for week, _, _, url in RELEASES:
        if fetch_one(week, url):
            ok += 1
        time.sleep(0.3)
    print(f"fetched {ok}/{len(RELEASES)} FluView weekly reports", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
