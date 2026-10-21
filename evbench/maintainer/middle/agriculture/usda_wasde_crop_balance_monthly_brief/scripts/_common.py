"""Shared helpers for usda_wasde_crop_balance_monthly_brief.

WASDE archive URLs (verified 2026-05-15) live on the ESMIS / Cornell Mann
Library mirror. The legacy `usda.gov/oce/commodity/wasde/wasde<MMYY>.pdf`
slug now 404s — see scenario.yaml.provenance.history for the migration
note.

Listing pages (HTML, paginated):
    https://esmis.nal.usda.gov/concern/publications/3t945q76s?locale=en&page=<N>

Each listing row exposes an absolute path of the form
    /sites/default/release-files/<bytes>/<bytes>/<bytes>/wasdeMMYY.pdf
which resolves to a PDF when fetched from esmis.nal.usda.gov.
"""
from __future__ import annotations
import os
import datetime as dt
import re
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
TS_SOURCE = SCENARIO_ROOT / "timeseries_source"
GT_SOURCE = SCENARIO_ROOT / "gt_source"
INSTANCES = SCENARIO_ROOT / "instances"
ENV = SCENARIO_ROOT / "environment"

ESMIS_HOST = "https://esmis.nal.usda.gov"
ESMIS_LISTING = f"{ESMIS_HOST}/concern/publications/3t945q76s?locale=en"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
    "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
}

MONTH_NAMES_LONG = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Regex: capture path + filename. The base name is `wasdeMMYY`; some
# releases publish a `v2` revision (e.g. `wasde0526v2.pdf`) — we prefer
# the v-suffixed variant when both exist.
_PDF_RE = re.compile(
    r'href="(/sites/default/release-files/[^"]+/wasde(\d{4})(v\d+)?\.pdf)"',
    re.IGNORECASE,
)


def iter_months(start_label: str, end_label: str):
    sy, sm = (int(x) for x in start_label.split("-"))
    ey, em = (int(x) for x in end_label.split("-"))
    cur = dt.date(sy, sm, 1)
    stop = dt.date(ey, em, 1)
    while cur <= stop:
        yield cur
        cur = dt.date(cur.year + (1 if cur.month == 12 else 0),
                      1 if cur.month == 12 else cur.month + 1, 1)


def month_label(d: dt.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_label_long(d: dt.date) -> str:
    return f"{MONTH_NAMES_LONG[d.month - 1]} {d.year}"


def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def discover_pdfs(max_pages: int = 12) -> dict[str, str]:
    """Scrape the ESMIS listing pages and return {YYYY-MM: absolute_url}.

    Prefers v-suffixed (revised) PDFs when multiple exist for a release.
    """
    found: dict[str, tuple[str, str]] = {}  # YYYY-MM -> (suffix, url)
    for page in range(max_pages):
        url = f"{ESMIS_LISTING}&page={page}"
        try:
            body = http_get(url).decode("utf-8", errors="replace")
        except Exception:
            continue
        new_this_page = 0
        for m in _PDF_RE.finditer(body):
            path, mmyy, suffix = m.group(1), m.group(2), (m.group(3) or "")
            mm, yy = mmyy[:2], mmyy[2:]
            try:
                month = int(mm)
                year = 2000 + int(yy)
                if not (1 <= month <= 12):
                    continue
            except ValueError:
                continue
            label = f"{year:04d}-{month:02d}"
            full_url = f"{ESMIS_HOST}{path}"
            prev = found.get(label)
            if prev is None or len(suffix) > len(prev[0]):
                found[label] = (suffix, full_url)
                new_this_page += 1
        if new_this_page == 0 and page > 0:
            # listing didn't grow → reached end
            break
    return {k: v[1] for k, v in found.items()}
