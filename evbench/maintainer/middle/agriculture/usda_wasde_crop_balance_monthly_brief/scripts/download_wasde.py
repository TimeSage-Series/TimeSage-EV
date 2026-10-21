"""Download historical USDA WASDE PDFs.

The legacy `https://www.usda.gov/oce/commodity/wasde/wasde<MMYY>.pdf` URL
pattern returns HTTP 404 as of mid-2025 — USDA migrated the WASDE archive
to the ESMIS / Cornell Mann Library mirror at

    https://esmis.nal.usda.gov/concern/publications/3t945q76s

Each release is exposed under
`/sites/default/release-files/<bytes>/<bytes>/<bytes>/wasdeMMYY.pdf` (older
months) or `/sites/default/release-files/<id>/wasdeMMYY.pdf` (newer
months). Some releases publish a `v2` revision (e.g. `wasde0526v2.pdf`)
when a published PDF is later corrected — we prefer the revised version.

This downloader:
  1. Scrapes paginated listing pages to map YYYY-MM → absolute URL.
  2. Downloads each PDF into `timeseries_source/wasde_pdfs/<orig_name>.pdf`
     (where <orig_name> mirrors the WASDE filename verbatim, including any
     v-suffix).
  3. Mirrors each download into `gt_source/<YYYY-MM>.pdf` per the brief's
     naming convention.

Idempotent — skips files that already exist with non-trivial size.
"""
from __future__ import annotations
import sys
from pathlib import Path
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    GT_SOURCE, HEADERS, TS_SOURCE, discover_pdfs, iter_months, month_label,
)

START_LABEL = "2022-01"   # earliest_raw_period from scenario.yaml
END_LABEL = "2026-05"     # last instance window month


def fetch_one(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 5000:
        return True
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        if len(data) < 5000:
            return False
        dest.write_bytes(data)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  miss: {url} ({exc})", file=sys.stderr)
        return False


def main() -> int:
    raw_dir = TS_SOURCE / "wasde_pdfs"
    raw_dir.mkdir(parents=True, exist_ok=True)
    GT_SOURCE.mkdir(parents=True, exist_ok=True)

    print("Scraping ESMIS listing pages...")
    catalog = discover_pdfs(max_pages=12)
    print(f"  found {len(catalog)} releases in catalog")

    ok = miss = 0
    for d in iter_months(START_LABEL, END_LABEL):
        label = month_label(d)
        url = catalog.get(label)
        if url is None:
            print(f"  {label}: no entry in ESMIS catalog (likely not yet released)")
            miss += 1
            continue
        orig_name = url.rsplit("/", 1)[-1]
        raw_dest = raw_dir / orig_name
        gt_dest = GT_SOURCE / f"{label}.pdf"
        if fetch_one(url, raw_dest):
            if not gt_dest.exists() or gt_dest.stat().st_size != raw_dest.stat().st_size:
                gt_dest.write_bytes(raw_dest.read_bytes())
            ok += 1
        else:
            miss += 1
    print(f"downloaded {ok} releases; {miss} misses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
