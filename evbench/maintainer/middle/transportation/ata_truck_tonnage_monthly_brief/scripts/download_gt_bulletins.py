"""Download per-month ATA Truck Tonnage Index press releases from the
Wayback Machine to gt_source/.

ATA publishes each monthly release at a slug like
  ata-truck-tonnage-index-<verb>-<percent>-<month>
e.g. "ata-truck-tonnage-index-rose-04-january" (Jan data) or
"ata-truck-tonnage-index-declined-15-march" (Mar data).

We use the CDX API to enumerate slugs ending in a month name, then
fetch each via Wayback. The data month is identified by the slug
trailing month-name token combined with the snapshot year.
"""
from __future__ import annotations
import os
import json, re, sys, time, urllib.request
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

MONTHS = ["january", "february", "march", "april", "may", "june",
          "july", "august", "september", "october", "november", "december"]
MONTH_TO_IDX = {m: i+1 for i, m in enumerate(MONTHS)}

CDX = (
    "https://web.archive.org/cdx/search/cdx"
    "?url=trucking.org/news-insights/ata-truck-tonnage"
    "&matchType=prefix&output=json"
    "&filter=statuscode:200&filter=mimetype:text/html"
    "&collapse=urlkey&limit=2000"
)


def fetch(url, timeout=60):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            print(f"    retry {i+1}: {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))
    return None


def detect_data_month_from_body(html: str) -> str | None:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    # ATA release body typically says e.g.
    # "ATA's For-Hire Truck Tonnage Index rose 0.4% in October ..."
    m = re.search(r"\b(?:rose|fell|increased|decreased|declined|jumped|surged|contracted|unchanged|edged|advanced)\b[^.]{0,30}\bin\s+(January|February|March|April|May|June|July|August|September|October|November|December)\b", text, re.IGNORECASE)
    if m:
        month = m.group(1).lower()
    else:
        m = re.search(r"\bin\s+(January|February|March|April|May|June|July|August|September|October|November|December)\b", text)
        if not m: return None
        month = m.group(1).lower()
    mi = MONTH_TO_IDX[month]
    # Try to find year near the month
    yr_m = re.search(r"(?:" + month + r"|" + month.title() + r")[, ]*(20[2-3]\d)", text)
    if yr_m:
        return f"{yr_m.group(1)}-{mi:02d}"
    return None


def main():
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    print("Fetching CDX index...", file=sys.stderr)
    cdx_body = fetch(CDX, timeout=90)
    if not cdx_body:
        print("CDX fetch failed", file=sys.stderr); return 1
    try:
        rows = json.loads(cdx_body)
    except Exception as e:
        print(f"CDX parse failed: {e}", file=sys.stderr); return 1
    if not rows:
        return 1
    hdr = rows[0]; ts_i=hdr.index('timestamp'); url_i=hdr.index('original')
    candidates: list[tuple[str, str]] = []
    for r in rows[1:]:
        u = r[url_i]; ts = r[ts_i]
        if ts < '20240301' or ts > '20260601':
            continue
        # Slug ends with a month name (after stripping query)
        base = u.split('?')[0]
        slug = base.rsplit('/', 1)[-1]
        if not re.search(r'-(january|february|march|april|may|june|july|august|september|october|november|december)(-\d+)?$', slug):
            continue
        candidates.append((ts, base))
    # De-dup by base URL — pick earliest timestamp (closest to release date).
    by_url: dict[str, str] = {}
    for ts, u in candidates:
        if u not in by_url or ts < by_url[u]:
            by_url[u] = ts
    print(f"  {len(by_url)} unique ATA tonnage URLs in window", file=sys.stderr)
    seen: set[str] = set()
    for u, ts in sorted(by_url.items(), key=lambda kv: kv[1]):
        wb = f"https://web.archive.org/web/{ts}/{u}"
        body = fetch(wb, timeout=90)
        if not body:
            continue
        html = body.decode("utf-8", errors="replace")
        data_month = detect_data_month_from_body(html)
        if not data_month:
            # Fall back to slug month + snapshot year
            slug = u.rsplit('/', 1)[-1]
            m = re.search(r'-(january|february|march|april|may|june|july|august|september|october|november|december)(?:-\d+)?$', slug)
            if not m:
                print(f"  WARN unknown month for {slug}", file=sys.stderr); continue
            mo = MONTH_TO_IDX[m.group(1)]
            # If snapshot is Jan-Feb, data is from prior calendar year for Nov/Dec releases
            snap_yr = int(ts[:4]); snap_mo = int(ts[4:6])
            data_y = snap_yr
            if mo >= snap_mo - 1:
                # Old data; if release should be ~next month, snap_mo > mo typical;
                # if snap_mo <= mo, then data is from previous year
                data_y = snap_yr - 1 if mo > snap_mo - 1 else snap_yr
            data_month = f"{data_y}-{mo:02d}"
        if data_month in seen:
            continue
        dst = GT_SOURCE / f"{data_month}.html"
        dst.write_bytes(body)
        seen.add(data_month)
        print(f"  ok {data_month}  <- {u} (ts {ts})", file=sys.stderr)
        time.sleep(1.5)
    print(f"Saved {len(seen)} ATA briefs.", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main() or 0)
