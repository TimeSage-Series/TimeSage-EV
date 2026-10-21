"""Ingest 24 USDA AMS Grain Transportation Report (GTR) weekly PDFs into
gt_source/. The GTR is the closest USDA-published narrative bulletin
covering the grain-export-inspections data this scenario tracks. The
scenario cadence is monthly but GTR is weekly — we take the last
available GTR issue published within each data month as the monthly
narrative representative.

Source: https://www.ams.usda.gov/sites/default/files/media/GTR<MMDDYYYY>.pdf

Note: GTR publication was suspended during the 2025-10 to 2025-11 govt
shutdown window. For those months, the closest pre-shutdown / first-
post-shutdown issue is substituted.

Saves each PDF as gt_source/<data-month>.pdf.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

# (data_month, gtr_release_mmddyyyy)
# Picks the GTR issue published in the last week of each data month.
# Verified live at https://www.ams.usda.gov/sites/default/files/media/GTR<MMDDYYYY>.pdf
RELEASES = [
    ("2024-04", "04252024"),
    ("2024-05", "05302024"),
    ("2024-06", "06272024"),
    ("2024-07", "07252024"),
    ("2024-08", "08292024"),
    ("2024-09", "09262024"),
    ("2024-10", "10242024"),
    ("2024-11", "11212024"),
    ("2024-12", "12262024"),
    ("2025-01", "01302025"),
    ("2025-02", "02272025"),
    ("2025-03", "03272025"),
    ("2025-04", "04172025"),  # late-April substitute (04242025 was 404)
    ("2025-05", "05222025"),  # late-May substitute (05292025 was 404)
    ("2025-06", "06262025"),
    ("2025-07", "07312025"),
    ("2025-08", "08282025"),
    ("2025-09", "09252025"),
    # Govt shutdown gap: 2025-10 had no GTR; 2025-11 first issue is 11202025.
    # Use 11202025 for both Oct and Nov data months (post-shutdown narrative
    # covers the catch-up period explicitly).
    ("2025-10", "11202025"),
    ("2025-11", "11202025"),
    ("2025-12", "12252025"),
    ("2026-01", "01292026"),
    ("2026-02", "02262026"),
    ("2026-03", "03262026"),
]


def fetch_one(data_month: str, release_mmddyyyy: str) -> bool:
    url = f"https://www.ams.usda.gov/sites/default/files/media/GTR{release_mmddyyyy}.pdf"
    dst = GT_SOURCE / f"{data_month}.pdf"
    if dst.exists() and dst.stat().st_size > 50_000:
        print(f"  {data_month} -> cached ({dst.stat().st_size} bytes)", file=sys.stderr)
        return True
    req = Request(url, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=60) as r:
            blob = r.read()
    except Exception as exc:  # noqa: BLE001
        print(f"  {data_month} -> FAIL: {exc}", file=sys.stderr)
        return False
    if len(blob) < 30_000 or not blob.startswith(b"%PDF"):
        print(f"  {data_month} -> bad payload ({len(blob)} bytes)", file=sys.stderr)
        return False
    dst.write_bytes(blob)
    print(f"  {data_month} -> {len(blob)} bytes", file=sys.stderr)
    return True


def main() -> int:
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    ok = 0
    for dmonth, rdate in RELEASES:
        if fetch_one(dmonth, rdate):
            ok += 1
        time.sleep(0.3)
    print(f"fetched {ok}/{len(RELEASES)} GTR PDFs", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
