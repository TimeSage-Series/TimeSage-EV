"""Ingest 21 historical FRB G.17 Industrial Production release PDFs (one per
data month) into gt_source/. Each PDF carries narrative commentary that
LLM judges can reference when grounding key_drivers / outlook_direction
fields.

Source: https://www.federalreserve.gov/releases/g17/<YYYYMMDD>/g17.pdf

Note: G.17 was not released during the Oct 2025 - Dec 2025 window (govt
shutdown period — verified empirically via URL scan). For those data
months, no separate PDF exists and the Jan 2026 release covers the gap.

Saves each PDF as gt_source/<data-month>.pdf (where data-month is the
month the PDF reports on, NOT the release date — the release date in
month M typically reports on data month M-1).
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

# (release_yyyymmdd, data_month) pairs. data_month is the month the
# release reports on; release date is the publication date.
# Empirically discovered via URL probe at https://www.federalreserve.gov/releases/g17/<YYYYMMDD>/g17.pdf
RELEASES = [
    # Release date     -> data-month-being-reported
    ("20240516", "2024-04"),  # May 16 release reports on April data
    ("20240618", "2024-05"),
    ("20240717", "2024-06"),
    ("20240815", "2024-07"),
    ("20240917", "2024-08"),
    ("20241017", "2024-09"),
    ("20241115", "2024-10"),
    ("20241217", "2024-11"),
    ("20250117", "2024-12"),
    ("20250214", "2025-01"),
    ("20250318", "2025-02"),
    ("20250416", "2025-03"),
    ("20250515", "2025-04"),
    ("20250617", "2025-05"),
    ("20250716", "2025-06"),
    ("20250815", "2025-07"),
    ("20250916", "2025-08"),
    # 2025-09, 2025-10, 2025-11, 2025-12 data months: NO separate G.17 PDF
    # was published (verified empirically — likely govt-shutdown gap).
    ("20260116", "2025-12"),  # Jan 2026 release reports on Dec 2025 data
    ("20260218", "2026-01"),
    ("20260316", "2026-02"),
    # 2026-03 data month would be reported around 2026-04-mid (not yet
    # released as of run date 2026-05-17 -- see audit notes).
]


def fetch_one(release_yyyymmdd: str, data_month: str) -> bool:
    url = f"https://www.federalreserve.gov/releases/g17/{release_yyyymmdd}/g17.pdf"
    dst = GT_SOURCE / f"{data_month}.pdf"
    if dst.exists() and dst.stat().st_size > 50_000:
        print(f"  {data_month} -> cached ({dst.stat().st_size} bytes)", file=sys.stderr)
        return True
    req = Request(url, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=60) as r:
            blob = r.read()
    except Exception as exc:  # noqa: BLE001
        print(f"  {data_month} -> FAIL ({release_yyyymmdd}): {exc}", file=sys.stderr)
        return False
    if len(blob) < 10_000 or not blob.startswith(b"%PDF"):
        print(f"  {data_month} -> bad payload ({len(blob)} bytes)", file=sys.stderr)
        return False
    dst.write_bytes(blob)
    print(f"  {data_month} -> {len(blob)} bytes", file=sys.stderr)
    return True


def main() -> int:
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    ok = 0
    for rdate, dmonth in RELEASES:
        if fetch_one(rdate, dmonth):
            ok += 1
        time.sleep(0.3)
    # Try to use Current for 2026-03 data month (April 2026 release).
    # Already covered: 20260218 reports Jan 2026, 20260316 reports Feb 2026.
    # For 2026-03 we expect a mid-April release.
    for rdate in ("20260415", "20260416", "20260417"):
        dst = GT_SOURCE / "2026-03.pdf"
        if dst.exists() and dst.stat().st_size > 50_000:
            break
        url = f"https://www.federalreserve.gov/releases/g17/{rdate}/g17.pdf"
        req = Request(url, headers={"User-Agent": UA})
        try:
            with urlopen(req, timeout=60) as r:
                blob = r.read()
            if blob.startswith(b"%PDF") and len(blob) > 10_000:
                dst.write_bytes(blob)
                print(f"  2026-03 -> {len(blob)} bytes via {rdate}", file=sys.stderr)
                ok += 1
                break
        except Exception:  # noqa: BLE001
            continue
    print(f"fetched {ok}/{len(RELEASES)+1} G.17 PDFs", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
