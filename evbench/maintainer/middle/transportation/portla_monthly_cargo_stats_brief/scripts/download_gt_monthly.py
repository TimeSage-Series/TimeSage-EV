"""Download per-month Port-of-LA cargo press releases to gt_source/.

Each Port-of-LA monthly cargo news release describes the PRIOR month's
TEU data. We map by the *data month* in the release body, save as
`gt_source/<YYYY-MM>.html` keyed to data month.

Source: portoflosangeles.org/news/cargo-news-briefings (live);
archived via web.archive.org. We use the Wayback CDX API to enumerate
historical snapshots, then fetch each via the Wayback URL template.

Naming convention in URLs:
  news_<MMDDYY>_<data_or_release_month>_cargo
where the slug may be either the data month or release month — we
disambiguate by reading the release body and looking for the
"<Month> <Year> loaded imports" pattern.
"""
from __future__ import annotations
import os
import json
import re
import sys
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
GT_SOURCE = SCENARIO_ROOT / "gt_source"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"

CDX_URL = (
    "https://web.archive.org/cdx/search/cdx"
    "?url=portoflosangeles.org/references/&matchType=prefix"
    "&output=json&from=20240101&to=20260601"
    "&filter=statuscode:200&filter=mimetype:text/html"
    "&collapse=urlkey&limit=10000"
)

MONTH_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(202[3-6])\s+loaded imports",
    re.IGNORECASE,
)
MONTHS_FULL = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def list_cargo_news_urls() -> list[tuple[str, str]]:
    """Return [(timestamp, original_url), ...] for *_cargo* releases."""
    body = http_get(CDX_URL, timeout=90).decode("utf-8", errors="replace")
    rows = json.loads(body)
    out: list[tuple[str, str]] = []
    if not rows:
        return out
    hdr = rows[0]
    ts_i, url_i = hdr.index("timestamp"), hdr.index("original")
    for r in rows[1:]:
        u = r[url_i]
        # Keep monthly cargo briefings only.
        if re.search(r"/news_\d{6}_[a-z]+_cargo(?:-en)?$", u):
            out.append((r[ts_i], u))
    return out


def fetch_via_wayback(ts: str, url: str) -> bytes:
    wb = f"https://web.archive.org/web/{ts}/{url}"
    return http_get(wb, timeout=90)


def detect_data_month(html: str) -> str | None:
    """Look for '<Month> <Year> loaded imports' to identify the
    data month covered by the release."""
    # Strip tags first for cleaner match.
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    m = MONTH_RE.search(text)
    if not m:
        return None
    mo = MONTHS_FULL.get(m.group(1).lower())
    yr = m.group(2)
    if not mo:
        return None
    return f"{yr}-{mo}"


def main() -> int:
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    print("Listing Port-LA cargo press release snapshots via CDX...", file=sys.stderr)
    urls = list_cargo_news_urls()
    print(f"  found {len(urls)} urlkeys", file=sys.stderr)
    seen: dict[str, tuple[str, str]] = {}
    for ts, u in urls:
        try:
            body = fetch_via_wayback(ts, u)
            html = body.decode("utf-8", errors="replace")
            data_month = detect_data_month(html)
            if not data_month:
                print(f"  WARN no data month for {u}", file=sys.stderr)
                continue
            # Prefer first non-empty fetch for a given data_month.
            # If duplicate (e.g. two press releases reference same month), keep first.
            if data_month in seen:
                continue
            dst = GT_SOURCE / f"{data_month}.html"
            dst.write_bytes(body)
            seen[data_month] = (ts, u)
            print(f"  ok {data_month}  <- {u}", file=sys.stderr)
            time.sleep(0.8)
        except Exception as exc:  # noqa
            print(f"  FAIL {u}: {exc}", file=sys.stderr)
            time.sleep(2.0)
    print(f"Saved {len(seen)} period briefs.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
