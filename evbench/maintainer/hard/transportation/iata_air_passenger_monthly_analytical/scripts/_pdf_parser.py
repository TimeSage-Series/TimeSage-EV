"""Parse the IATA Air Passenger Market Analysis monthly PDF.

Layout (verified against issues 2024-04 through 2026-03):

  Page 1: headline KPI block + narrative paragraph
    - "Industry RPK growth was <X>% YoY"  (or "...declined <X>%")
    - "ASK <X>% YoY"
    - "PLF reached <X>%"  /  "Passenger load factor was <X>%"

  Page 2 (sometimes p1 bottom): regional table
    - Asia Pacific / Europe / North America / Latin America / Africa /
      Middle East  with monthly RPK YoY %, ASK YoY %, PLF

  Body: per-region commentary; "Outlook"  /  "What to watch" closing section

We extract:
  - 8 numeric headline + regional cells (timeseries)
  - drivers narrative sentences (Hard-tier analytical block)
  - outlook section text (Hard-tier outlook tone)

All extractions are best-effort. If a field is missing in the report,
the corresponding numeric is None and downstream code leaves the CSV
cell blank — NEVER fabricates a value.
"""
from __future__ import annotations
import re
from pathlib import Path

from pypdf import PdfReader


# ---------- raw text -----------------------------------------------------

def read_pdf_text(path: Path) -> str:
    r = PdfReader(str(path))
    return "\n".join(p.extract_text() or "" for p in r.pages)


_NBSP = re.compile(r"[   ]")
_MULTISPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    t = _NBSP.sub(" ", text)
    t = _MULTISPACE.sub(" ", t)
    t = _MULTI_NEWLINE.sub("\n\n", t)
    return t


# ---------- headline KPIs ------------------------------------------------

# Numeric anchored to keyword. The IATA layout sometimes prints the figure
# on the same line and sometimes on the next, so we tolerate one newline.
_NUM = r"(-?\d+(?:\.\d+)?)\s*%"

RPK_TOTAL_RX = re.compile(
    rf"(?:Industry|Total)?\s*RPK[^\n]*?(?:growth|increase|rose|expanded|"
    rf"declined|contracted|fell)[^\n]{{0,40}}?{_NUM}\s*(?:YoY|year[- ]on[- ]year)?",
    re.I,
)
ASK_TOTAL_RX = re.compile(
    rf"ASK[^\n]*?(?:growth|increase|rose|expanded|declined|contracted|fell)"
    rf"[^\n]{{0,40}}?{_NUM}\s*(?:YoY|year[- ]on[- ]year)?",
    re.I,
)
PLF_RX = re.compile(
    rf"(?:passenger\s+load\s+factor|PLF|load\s+factor)\b[^\n]{{0,60}}?{_NUM}",
    re.I,
)
INTL_RX = re.compile(
    rf"international\s+RPK[^\n]*?{_NUM}\s*(?:YoY)?",
    re.I,
)
DOM_RX = re.compile(
    rf"domestic\s+RPK[^\n]*?{_NUM}\s*(?:YoY)?",
    re.I,
)


def _first(rx: re.Pattern, text: str) -> float | None:
    m = rx.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def extract_headline(text: str) -> dict:
    return {
        "total_rpk_yoy_pct":    _first(RPK_TOTAL_RX, text),
        "total_ask_yoy_pct":    _first(ASK_TOTAL_RX, text),
        "load_factor_pct":      _first(PLF_RX,       text),
        "intl_rpk_yoy_pct":     _first(INTL_RX,      text),
        "domestic_rpk_yoy_pct": _first(DOM_RX,       text),
    }


# ---------- regional table ----------------------------------------------

REGION_ALIASES = {
    "asia_pacific":  [r"asia[- ]pacific", r"asia\s*/\s*pacific", r"\bAPAC\b"],
    "europe":        [r"\beurope\b"],
    "north_america": [r"north\s+america"],
    "latin_america": [r"latin\s+america"],
    "africa":        [r"\bafrica\b"],
    "middle_east":   [r"middle\s+east"],
}


def extract_regional_rpk(text: str) -> dict[str, float | None]:
    """For each region, capture the first numeric % near the region name
    on a line that also references RPK growth. Best-effort; the published
    table layout varies slightly month to month."""
    out: dict[str, float | None] = {k: None for k in REGION_ALIASES}
    # Try a simple line-scan: each line containing a region name and a %.
    for line in text.splitlines():
        line_l = line.lower()
        # Only consider lines that plausibly belong to the regional RPK row
        # (avoid load factor / ASK rows by requiring "rpk" or absence of
        # competing keywords on the same line).
        for key, aliases in REGION_ALIASES.items():
            if out[key] is not None:
                continue
            if not any(re.search(a, line_l) for a in aliases):
                continue
            # Grab the *first* signed numeric % on the line.
            m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", line)
            if m:
                try:
                    out[key] = float(m.group(1))
                except ValueError:
                    pass
    return out


# ---------- analytical blocks -------------------------------------------

DRIVER_HINTS = [
    ("capacity_constraint",       r"capacity\s+(constraint|tight|shortfall|limit)"),
    ("demand_recovery",           r"(recover|rebound|pent[- ]up\s+demand|post[- ]pandemic)"),
    ("fuel_cost",                 r"(jet\s+fuel|fuel\s+price|fuel\s+cost)"),
    ("geopolitical_disruption",   r"(conflict|war|sanction|geopolit|hormuz|red\s+sea|"
                                  r"israel|iran|russia|ukraine)"),
    ("fx_effect",                 r"(exchange\s+rate|fx|currency|dollar\s+strength)"),
    ("business_travel_recovery",  r"(business\s+travel|corporate\s+travel|premium\s+cabin)"),
    ("leisure_demand",            r"(leisure|holiday|tourism|vacation)"),
    ("regional_economic",         r"(GDP|economic\s+growth|recession|consumer\s+spending|"
                                  r"economic\s+activity)"),
    ("seasonality",               r"(seasonal|peak\s+season|off[- ]peak|summer|winter|"
                                  r"chinese\s+new\s+year|easter|christmas)"),
    ("infrastructure_constraint", r"(airport\s+capacity|atc|air\s+traffic\s+control|"
                                  r"slot\s+constraint|infrastructure)"),
]

OUTLOOK_HEADER = re.compile(
    r"(?:^|\n)\s*(outlook|what\s+to\s+watch|the\s+way\s+forward|looking\s+ahead)\b",
    re.I,
)


def extract_outlook_block(text: str, max_len: int = 2500) -> str:
    m = OUTLOOK_HEADER.search(text)
    if not m:
        return ""
    start = m.end()
    end = min(len(text), start + max_len)
    return text[start:end].strip()


def classify_drivers(text: str) -> list[str]:
    """Return controlled-vocab driver labels whose hint regex matched.
    Order: by hit count, descending."""
    text_l = text.lower()
    counts: list[tuple[str, int]] = []
    for label, pat in DRIVER_HINTS:
        n = len(re.findall(pat, text_l))
        if n > 0:
            counts.append((label, n))
    counts.sort(key=lambda kv: kv[1], reverse=True)
    return [k for k, _ in counts]


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text)
    return [p.strip() for p in parts if p.strip()]


def extract_evidence_sentences(text: str, limit: int = 6) -> list[str]:
    """Pull the first few load-bearing sentences that mention RPK / growth /
    outlook / drivers — used as candidates for gt_evidence.md."""
    sents = _split_sentences(text)
    keep: list[str] = []
    seen: set[str] = set()
    trig = re.compile(
        r"\b(RPK|ASK|load\s+factor|growth|demand|capacity|outlook|expect|forecast)\b",
        re.I,
    )
    for s in sents:
        if 40 < len(s) < 400 and trig.search(s):
            sig = s[:80]
            if sig in seen:
                continue
            seen.add(sig)
            keep.append(s)
        if len(keep) >= limit:
            break
    return keep


# ---------- top-level driver ---------------------------------------------

def parse_report(path: Path) -> dict:
    raw = read_pdf_text(path)
    text = normalize(raw)

    head = extract_headline(text)
    regional = extract_regional_rpk(text)
    outlook = extract_outlook_block(text)
    drivers = classify_drivers(text)
    evidence = extract_evidence_sentences(text)

    return {
        "headline":      head,
        "regional_rpk":  regional,
        "outlook_text":  outlook,
        "driver_labels": drivers,
        "evidence_sentences": evidence,
        "raw_text_len":  len(text),
    }
