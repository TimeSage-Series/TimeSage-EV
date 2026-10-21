"""Discover Freightos weekly-freight-update URLs via the post sitemap.

The index page only lists 10 most-recent posts and lacks working pagination,
but /post-sitemap.xml lists every published post. We pull the sitemap, filter
to weekly-freight-updates URLs, parse the publication date from each slug,
and emit a JSON list sorted newest-first.

Output: scripts/_discovered_urls.json
  [{"date": "2026-05-12", "slug": "...", "url": "..."}, ...]
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from _common import HEADERS, MONTH_NAMES  # noqa: E402

SITEMAP_URL = "https://www.freightos.com/post-sitemap.xml"
OUT = Path(__file__).parent / "_discovered_urls.json"

URL_RE = re.compile(
    r"<loc>(https://www\.freightos\.com/freight-industry-updates/"
    r"weekly-freight-updates/([a-z0-9\-]+))/?</loc>"
)

DATE_PATTERNS = [
    # asia-europe-...-may-5-2026-update
    re.compile(r"-(" + "|".join(MONTH_NAMES) + r")-(\d{1,2})-(\d{4})-update$"),
    # september-26-2023-update
    re.compile(r"^(" + "|".join(MONTH_NAMES) + r")-(\d{1,2})-(\d{4})-update$"),
    # update-july-11-2023
    re.compile(r"^update-(" + "|".join(MONTH_NAMES) + r")-(\d{1,2})-(\d{4})$"),
]


def parse_slug(slug: str) -> tuple[int, int, int] | None:
    for rx in DATE_PATTERNS:
        m = rx.search(slug)
        if m:
            month_word, day, year = m.group(1), int(m.group(2)), int(m.group(3))
            return year, MONTH_NAMES[month_word], day
    return None


def main() -> None:
    r = requests.get(SITEMAP_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    records: list[dict] = []
    for full_url, slug in URL_RE.findall(r.text):
        d = parse_slug(slug)
        if not d:
            continue
        y, m, day = d
        records.append({
            "date": f"{y:04d}-{m:02d}-{day:02d}",
            "slug": slug,
            "url": full_url if full_url.endswith("/") else full_url + "/",
        })
    records.sort(key=lambda r: r["date"], reverse=True)
    # dedupe by date keeping first (newest variant)
    seen_dates: set[str] = set()
    deduped: list[dict] = []
    for rec in records:
        if rec["date"] in seen_dates:
            continue
        seen_dates.add(rec["date"])
        deduped.append(rec)
    OUT.write_text(json.dumps(deduped, indent=2))
    print(f"[done] {len(deduped)} URLs (from {len(records)} sitemap entries) → {OUT}",
          flush=True)
    print(f"[range] {deduped[-1]['date']} → {deduped[0]['date']}", flush=True)


if __name__ == "__main__":
    main()
