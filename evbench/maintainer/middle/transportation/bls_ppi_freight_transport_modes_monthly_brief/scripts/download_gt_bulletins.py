"""Download per-month BLS Producer Price Index news-release PDFs to
gt_source/<YYYY-MM>.pdf.

BLS direct fetch is blocked by Akamai for non-browser User-Agents
(returns 403), so we use the Wayback Machine's CDX API to enumerate
archived snapshots of `bls.gov/news.release/archives/ppi_*.pdf` and
download the raw bytes via Wayback's `if_` rewrite. The data month is
detected by parsing page-1 of each PDF and matching
`PRODUCER PRICE INDEXES – <MONTH> <YEAR>`.

Filename convention: `ppi_<MMDDYYYY>.pdf`, where MMDDYYYY is the
RELEASE date (typically mid-month, covering the prior month's PPI).
The detected data-month tag in the PDF header determines the output
filename, not the release date — which correctly handles
shutdown-delayed releases.

Files saved as `gt_source/<YYYY-MM>.pdf` keyed to the DATA month.

Replaces the prior Wayback-HTML approach (which captured the `ppi.htm`
landing page wrapped in BLS site chrome rather than clean
news-release PDFs).
"""
from __future__ import annotations
import os
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

from pypdf import PdfReader  # type: ignore

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
STEM = "ppi"

# Release-window pad: data window 2024-05..2026-04 → release window
# 2024-06..2026-05. Pad each side by ~1 month for slack.
WINDOW_START = "20240501"
WINDOW_END = "20260728"

_MONTHS = ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]
MONTH_TO_IDX = {m.upper(): i + 1 for i, m in enumerate(_MONTHS)}

DETECT = re.compile(r"PRODUCER\s+PRICE\s+INDEX(?:ES)?\s*[—–\-]+\s*([A-Z]+)\s+(20\d{2})",
                    re.IGNORECASE)


def fetch(url: str, timeout: int = 120, retries: int = 3) -> bytes | None:
    err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2.0 * (i + 1))
    print(f"    fetch fail {url[:90]}: {err}", file=sys.stderr)
    return None


def detect_data_month(pdf_bytes: bytes) -> str | None:
    tmp = Path("/tmp/_ppi_probe.pdf")
    tmp.write_bytes(pdf_bytes)
    try:
        r = PdfReader(str(tmp))
    except Exception as e:  # noqa: BLE001
        print(f"    pypdf parse fail: {e}", file=sys.stderr)
        return None
    text = ""
    for p in r.pages[:3]:
        try:
            text += (p.extract_text() or "") + "\n"
        except Exception:  # noqa: BLE001
            continue
    m = DETECT.search(text)
    if not m:
        return None
    mon, yr = m.group(1), m.group(2)
    midx = MONTH_TO_IDX.get(mon.upper())
    if not midx:
        return None
    return f"{yr}-{midx:02d}"


def cdx_search() -> list[dict]:
    url = (
        "https://web.archive.org/cdx/search/cdx?"
        f"url=www.bls.gov/news.release/archives/{STEM}_*"
        f"&from={WINDOW_START}&to={WINDOW_END}"
        "&output=json&filter=statuscode:200&filter=mimetype:application/pdf"
        "&collapse=urlkey"
    )
    body = fetch(url, timeout=60)
    if not body:
        return []
    try:
        rows = json.loads(body)
    except Exception as e:  # noqa: BLE001
        print(f"    CDX parse fail: {e}", file=sys.stderr)
        return []
    out = []
    for row in rows[1:]:
        ts, original = row[1], row[2]
        m = re.search(rf"{STEM}_(\d{{2}})(\d{{2}})(\d{{4}})\.pdf", original)
        if not m:
            continue
        mm, dd, yyyy = m.groups()
        try:
            rel = date(int(yyyy), int(mm), int(dd))
        except ValueError:
            continue
        out.append({"ts": ts, "url": original, "release": rel})
    out.sort(key=lambda r: r["release"], reverse=True)
    return out


def main() -> int:
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    captures = cdx_search()
    print(f"  CDX: {len(captures)} captures", file=sys.stderr)
    seen: set[str] = set()
    log: dict[str, str] = {}
    for cap in captures:
        url = f"http://web.archive.org/web/{cap['ts']}if_/{cap['url']}"
        body = fetch(url, timeout=120)
        if not body or not body.startswith(b"%PDF"):
            continue
        dm = detect_data_month(body)
        if not dm:
            print(f"    no data-month anchor in {cap['url']}", file=sys.stderr)
            continue
        if dm in seen:
            continue
        (GT_SOURCE / f"{dm}.pdf").write_bytes(body)
        seen.add(dm)
        log[dm] = f"ok release={cap['release'].isoformat()} ts={cap['ts']}"
        print(f"  ok {dm} <- {cap['url'].split('/')[-1]}", file=sys.stderr)
        time.sleep(0.5)
    print(json.dumps(log, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
