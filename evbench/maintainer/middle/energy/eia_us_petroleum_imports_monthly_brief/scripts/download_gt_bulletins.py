"""Download per-month EIA Petroleum Supply Monthly (PSM) PDFs to
gt_source/.

EIA archives historical PSM PDFs at a predictable URL:
  https://www.eia.gov/petroleum/supply/monthly/archive/<release_year>/<release_year>_<MM>/pdf/psmall.pdf

The PSM release for May <Y> reports March <Y> data (i.e. data is from
~2 months prior to the release month). We map each desired data month
to its release date and save as `gt_source/<YYYY-MM>.html` (renamed
`.pdf` per source).
"""
from __future__ import annotations
import os
import sys, time, urllib.request
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
GT_SOURCE = SCENARIO_ROOT / "gt_source"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


def fetch(url, timeout=120):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            print(f"    retry {i+1}: {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))
    return None


def main():
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    # Data months 2024-03 .. 2026-02 → release months data + 2.
    y, m = 2024, 3
    seen = 0
    for _ in range(24):
        rel_y, rel_m = y, m + 2
        if rel_m > 12:
            rel_m -= 12; rel_y += 1
        url = f"https://www.eia.gov/petroleum/supply/monthly/archive/{rel_y:04d}/{rel_y:04d}_{rel_m:02d}/pdf/psmall.pdf"
        key = f"{y:04d}-{m:02d}"
        dst = GT_SOURCE / f"{key}.pdf"
        if dst.exists() and dst.stat().st_size > 100000:
            seen += 1
        else:
            body = fetch(url)
            if not body:
                print(f"  FAIL {key} <- {url}", file=sys.stderr)
            else:
                dst.write_bytes(body)
                seen += 1
                print(f"  ok {key} ({len(body)} bytes) <- {url}", file=sys.stderr)
            time.sleep(0.8)
        m += 1
        if m == 13:
            m = 1; y += 1
    # Try latest months too — March 2026 data should be released May 2026
    print(f"Saved {seen}", file=sys.stderr)


if __name__ == "__main__":
    main()
