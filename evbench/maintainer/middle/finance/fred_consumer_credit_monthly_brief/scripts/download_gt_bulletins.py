"""Download per-month Federal Reserve G.19 Consumer Credit news-release
PDFs to gt_source/<YYYY-MM>.pdf.

The Federal Reserve publishes the monthly G.19 Consumer Credit release
as a PDF at federalreserve.gov/releases/g19/<YYYYMMDD>/g19.pdf, where
<YYYYMMDD> is the release date. Each PDF is the full news release
(narrative + tables) for one data month, which typically corresponds
to the release date minus ~2 months. The PDF URL is publicly
accessible via direct HTTP (no Wayback Machine needed), although
Cloudflare requires a real User-Agent header.

The data month for each PDF is detected by parsing page-1 of the PDF
and matching the "In <Month>, consumer credit ..." narrative line or
the metadata "<Month> <Year> <Release date>" line under the
"Consumer Credit For release at..." header.

Files saved as `gt_source/<YYYY-MM>.pdf` keyed to the DATA month.

Replaces the prior Wayback-HTML approach (which produced
landing-page captures with site-chrome rather than clean
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

_MONTHS = ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]
MONTH_TO_IDX = {m.upper(): i + 1 for i, m in enumerate(_MONTHS)}
_MONTHS_RE = "|".join(_MONTHS)

# Data-month detection patterns (page-1 text), tried in order.
DETECT_PATTERNS = [
    # Old (pre-mid-2024) layout: "Consumer Credit\nJanuary 2024"
    re.compile(rf"Consumer\s+Credit\s*[\r\n]+\s*({_MONTHS_RE})\s+(20\d{{2}})",
               re.IGNORECASE | re.MULTILINE),
    # Narrative anchor: "In <Month>, consumer credit ..."  (year resolved nearby)
    re.compile(rf"\bIn\s+({_MONTHS_RE}),\s+consumer\s+credit", re.IGNORECASE),
    # New layout fallback: metadata line under "For release at..."
    re.compile(rf"For\s+release\s+at[^\n]*\s*[\r\n]+\s*({_MONTHS_RE})\s+(20\d{{2}})",
               re.IGNORECASE | re.MULTILINE),
]


def fetch(url: str, timeout: int = 60) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:  # noqa: BLE001
        print(f"    fetch fail {url[:90]}: {e}", file=sys.stderr)
        return None


def detect_data_month(pdf_bytes: bytes) -> str | None:
    tmp = Path("/tmp/_g19_probe.pdf")
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
    for pat in DETECT_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        groups = m.groups()
        if len(groups) >= 2 and groups[1]:
            mon, yr = groups[0], groups[1]
        else:
            mon = groups[0]
            ym = re.search(rf"\b{re.escape(mon)}\s+(20\d{{2}})\b", text, re.IGNORECASE)
            if not ym:
                continue
            yr = ym.group(1)
        midx = MONTH_TO_IDX.get(mon.upper())
        if not midx:
            continue
        return f"{yr}-{midx:02d}"
    return None


def main() -> int:
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    # Data months 2024-01 through 2026-03 → release dates roughly
    # 2024-03 through 2026-05. Probe each candidate release day (4..13).
    seen: set[str] = set()
    log: dict[str, str] = {}
    rel_start = date(2024, 1, 1)
    rel_end = date(2026, 6, 1)
    d = rel_start
    while d < rel_end:
        for day in range(4, 14):
            try:
                rel = date(d.year, d.month, day)
            except ValueError:
                continue
            url = f"https://www.federalreserve.gov/releases/g19/{rel.strftime('%Y%m%d')}/g19.pdf"
            body = fetch(url)
            if not body or not body.startswith(b"%PDF"):
                continue
            dm = detect_data_month(body)
            if not dm:
                print(f"    no data-month anchor in {url}", file=sys.stderr)
                continue
            if dm in seen:
                continue
            (GT_SOURCE / f"{dm}.pdf").write_bytes(body)
            seen.add(dm)
            log[dm] = f"ok release={rel.isoformat()}"
            print(f"  ok {dm} <- {rel.isoformat()}", file=sys.stderr)
            time.sleep(0.3)
        # Advance one month
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)
    print(json.dumps(log, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
