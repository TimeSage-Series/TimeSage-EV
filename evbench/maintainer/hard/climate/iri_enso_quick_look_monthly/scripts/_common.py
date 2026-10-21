"""Shared helpers for the iri_enso_quick_look_monthly scenario."""
from __future__ import annotations
import os
import calendar
import datetime as dt
import re
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

# Per-issue URL pattern. Each ENSO Diagnostic Discussion is published on
# the 2nd Thursday of its issue month at a stable URL with lowercase
# 3-letter month + 4-digit year.
ISSUE_URL_FMT = (
    "https://iri.columbia.edu/our-expertise/climate/forecasts/"
    "enso/{year}-{month_long}-quick-look/"
)

# Canonical ONI machine-readable. Used as the backing time-series for
# the per-instance CSV (cumulative Niño 3.4 SST anomaly history).
ONI_TXT_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"

# Optional: reuse cached ONI from the Easy ONI scenario if present.
ONI_CACHE_CANDIDATES = [
    SCENARIO_ROOT.parents[2] / "easy" / "climate"
    / "noaa_cpc_oni_global_enso_phase" / "timeseries_source",
]

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,text/plain,*/*;q=0.9",
    "Accept-Language": "en-US,en;q=0.9",
}

IRI_REQUEST_SLEEP_SEC = 1.0     # polite gap between cpc.ncep.noaa.gov calls

ALERT_STATUS_OPTIONS = [
    "El Niño Advisory",
    "La Niña Advisory",
    "El Niño Watch",
    "La Niña Watch",
    "Final El Niño Advisory",
    "Final La Niña Advisory",
    "Not Active",
]

# Map ASCII variants → canonical Unicode form (parser may see either)
ALERT_STATUS_NORMALIZE = {
    "El Nino Advisory": "El Niño Advisory",
    "La Nina Advisory": "La Niña Advisory",
    "El Nino Watch": "El Niño Watch",
    "La Nina Watch": "La Niña Watch",
    "Final El Nino Advisory": "Final El Niño Advisory",
    "Final La Nina Advisory": "Final La Niña Advisory",
}


# --- period helpers --------------------------------------------------------

def period_to_month_long(period: str) -> tuple[str, int]:
    """'2025-04' -> ('april', 2025) for the IRI URL slug."""
    y, m = period.split("-")
    return calendar.month_name[int(m)].lower(), int(y)


def period_to_mmm_yyyy(period: str) -> tuple[str, int]:
    """'2025-01' → ('jan', 2025)."""
    y, m = period.split("-")
    return calendar.month_abbr[int(m)].lower(), int(y)


def iter_months(start: str, end: str):
    """Yield 'YYYY-MM' inclusive."""
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            m = 1; y += 1


def month_long(period: str) -> str:
    y, m = (int(x) for x in period.split("-"))
    return f"{calendar.month_name[m]} {y}"


# --- HTML / ONI parsing ---------------------------------------------------

def html_to_text(html: str) -> str:
    s = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    repl = {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&#37;": "%", "&deg;": "°", "&ndash;": "–", "&mdash;": "—",
        "&quot;": '"', "&#39;": "'", "&apos;": "'",
        "&ntilde;": "ñ", "&Ntilde;": "Ñ",
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# ONI ascii parser (mirrors the Easy ONI scenario's helper)
SEASON_CENTERED_MONTH = {
    "DJF":  1, "JFM":  2, "FMA":  3, "MAM":  4, "AMJ":  5, "MJJ":  6,
    "JJA":  7, "JAS":  8, "ASO":  9, "SON": 10, "OND": 11, "NDJ": 12,
}


def parse_oni_ascii(text: str) -> list[dict]:
    rows: list[dict] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("SEAS"):
            continue
        parts = s.split()
        if len(parts) != 4 or parts[0] not in SEASON_CENTERED_MONTH:
            continue
        try:
            rows.append({
                "season": parts[0],
                "year": int(parts[1]),
                "total_sst_c": float(parts[2]),
                "anomaly_c": float(parts[3]),
            })
        except ValueError:
            continue
    return rows


def season_centered_date(season: str, year: int) -> dt.date:
    return dt.date(year, SEASON_CENTERED_MONTH[season], 15)
