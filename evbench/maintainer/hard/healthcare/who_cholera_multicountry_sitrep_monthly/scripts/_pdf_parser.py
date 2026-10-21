"""Parse a WHO Multi-country cholera SitRep / Epidemiological Update PDF
into structured Hard-tier fields.

The PDFs follow a recurring layout:
  - Top-of-page header with a "Global risk – Very high / High / Moderate / Low" badge
  - "Situation overview" or "Global epidemiological update" header
  - Cumulative figures: "<N> cholera cases", "<N> deaths", "<N> countries"
  - "Population at risk – <N> billion"
  - Month-over-month phrasing: "showing a <N>% (increase|decrease) from the previous month"
  - Regional table: WHO region -> case count
  - Recommendations / WHO advice / Public health response paragraphs
  - "Outlook" / "in the coming months" / "expected" paragraphs

The parser is regex/keyword-driven against the raw extracted text. WHO's PDF
text extraction order is mostly stable; where layout breaks an extraction we
fall back to a wider character window. All extractions are best-effort and
documented in gt_evidence.md so the LLM judge can verify against the source.
"""
from __future__ import annotations
import re
from pathlib import Path

from pypdf import PdfReader


# ---------- core text extraction ----------------------------------------

def read_pdf_text(path: Path) -> str:
    r = PdfReader(str(path))
    return "\n".join(p.extract_text() or "" for p in r.pages)


# Normalize the heavy non-breaking-space and stray whitespace WHO PDFs emit.
_NBSP = re.compile(r"[    ]")
_MULTISPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    t = _NBSP.sub(" ", text)
    t = _MULTISPACE.sub(" ", t)
    t = _MULTI_NEWLINE.sub("\n\n", t)
    return t


# ---------- atomic Hard-tier fields -------------------------------------

GLOBAL_RISK_PATTERNS = [
    re.compile(r"Global\s+risk\s*[\-–—:]\s*(Very\s+high|High|Moderate|Low)", re.I),
    re.compile(r"WHO\s+has\s+assessed\s+the\s+global\s+public\s+health\s+risk\s+as\s+(very\s+high|high|moderate|low)", re.I),
    re.compile(r"global\s+public\s+health\s+risk\s+(?:posed|presented)\s+by\s+this\s+event\s+as\s+(very\s+high|high|moderate|low)", re.I),
]


def extract_global_risk(text: str) -> str | None:
    for rx in GLOBAL_RISK_PATTERNS:
        m = rx.search(text)
        if m:
            return m.group(1).lower().replace("  ", " ").replace(" ", "_")
    return None


# "a cumulative total of 614,828 cholera cases and 7,598 deaths"
CUM_CASES_DEATHS = re.compile(
    r"cumulative\s+total\s+of\s+([\d, \s]+)\s+cholera(?:\s+and\s+(?:AWD|acute\s+watery\s+diarrhoea|acute\s+watery\s+diarrhea))?\s+cases\s+and\s+([\d, \s]+)\s+deaths",
    re.I,
)
# "from 33 countries across five WHO regions"
COUNTRY_COUNT = re.compile(
    r"from\s+(\d+)\s+countries(?:,?\s+territories(?:\s+and\s+areas)?)?\s+across\s+(?:\w+)\s+WHO\s+regions?",
    re.I,
)
# "CFR 1.2%" or "case fatality ratio (CFR) of 1.2%"
CFR_PATTERNS = [
    re.compile(r"case\s+fatality\s+rat(?:io|e)\s*\(?CFR\)?\s+of\s+([\d.]+)\s*%", re.I),
    re.compile(r"CFR\s+of\s+([\d.]+)\s*%", re.I),
    re.compile(r"CFR\s*[:=]\s*([\d.]+)\s*%", re.I),
]
# "Population at risk – 1 billion" / "Population at risk: 1.2 billion"
POP_AT_RISK = re.compile(
    r"Population\s+at\s+risk\s*[\-–—:]?\s*([\d.,]+)\s*(billion|million)",
    re.I,
)
# "a 25% decrease from the previous month" / "25% increase from November"
MOM_CHANGE = re.compile(
    r"(?:showing\s+a\s+|representing\s+a\s+)?(\d+(?:\.\d+)?)\s*%\s+(increase|decrease)\s+(?:from\s+(?:the\s+previous\s+month|[A-Z][a-z]+(?:\s+\d{4})?))",
    re.I,
)


def _to_int(s: str) -> int | None:
    s = s.replace(",", "").replace(" ", "").replace(" ", "").strip()
    return int(s) if s.isdigit() else None


def extract_cumulative_cases_deaths(text: str) -> tuple[int | None, int | None]:
    m = CUM_CASES_DEATHS.search(text)
    if not m:
        return None, None
    return _to_int(m.group(1)), _to_int(m.group(2))


def extract_countries_reporting(text: str) -> int | None:
    m = COUNTRY_COUNT.search(text)
    return int(m.group(1)) if m else None


def extract_cfr_pct(text: str) -> float | None:
    for rx in CFR_PATTERNS:
        m = rx.search(text)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                continue
    # Derive from cases/deaths if both available
    cases, deaths = extract_cumulative_cases_deaths(text)
    if cases and deaths and cases > 0:
        return round(100.0 * deaths / cases, 2)
    return None


def extract_population_at_risk(text: str) -> str | None:
    m = POP_AT_RISK.search(text)
    if not m:
        return None
    return f"{m.group(1).strip()} {m.group(2).lower()}"


def extract_mom_change(text: str) -> tuple[float | None, str | None]:
    """Return (signed_pct, direction). 'increase' -> positive, 'decrease' -> negative.

    Picks the FIRST month-over-month phrase, which is virtually always the
    headline figure for new monthly cases.
    """
    m = MOM_CHANGE.search(text)
    if not m:
        return None, None
    val = float(m.group(1))
    direction = m.group(2).lower()
    signed = val if direction == "increase" else -val
    return signed, direction


# ---------- regional breakdown ------------------------------------------

WHO_REGIONS = [
    ("african",         re.compile(r"African\s+Region", re.I)),
    ("eastern_mediterranean", re.compile(r"Eastern\s+Mediterranean\s+Region", re.I)),
    ("south_east_asia", re.compile(r"South[-\s]?East\s+Asia\s+Region", re.I)),
    ("americas",        re.compile(r"Region\s+of\s+the\s+Americas|Americas\s+Region", re.I)),
    ("european",        re.compile(r"European\s+Region", re.I)),
    ("western_pacific", re.compile(r"Western\s+Pacific\s+Region", re.I)),
]


def extract_regional_breakdown(text: str) -> list[dict]:
    """Best-effort: pull (region, case_count) tuples from sentences that
    mention each region and a number nearby."""
    out: list[dict] = []
    for key, rx in WHO_REGIONS:
        m = rx.search(text)
        if not m:
            continue
        # Look at a +/-180 char window for a "N,NNN cases" style phrase
        start = max(0, m.start() - 180)
        end = min(len(text), m.end() + 180)
        window = text[start:end]
        num_match = re.search(r"([\d,]{2,})\s+(?:cases|new\s+cases|cholera\s+cases)", window)
        cases = _to_int(num_match.group(1)) if num_match else None
        out.append({"region": key, "cases": cases, "context": window.strip()})
    return out


def extract_regions_with_outbreak(text: str) -> list[str]:
    """Return canonical region keys that appear at least once in the PDF."""
    present = []
    for key, rx in WHO_REGIONS:
        if rx.search(text):
            present.append(key)
    return present


# ---------- analytical (Hard-tier) extracted text -----------------------

# Headers we anchor extraction off
SITUATION_OVERVIEW_HEADERS = [
    re.compile(r"(?i)Global\s+epidemiological\s+update"),
    re.compile(r"(?i)Situation\s+overview"),
    re.compile(r"(?i)Global\s+situation"),
]
RECOMMENDATIONS_HEADERS = [
    re.compile(r"(?i)WHO\s+recommendations?"),
    re.compile(r"(?i)Recommendations\s+for"),
    re.compile(r"(?i)WHO\s+advice"),
    re.compile(r"(?i)Public\s+health\s+response"),
]
OUTLOOK_HEADERS = [
    re.compile(r"(?i)Outlook"),
    re.compile(r"(?i)Looking\s+ahead"),
    re.compile(r"(?i)In\s+the\s+coming\s+(?:weeks|months)"),
]


def _slice_after(text: str, header_rx: re.Pattern, length: int) -> str:
    m = header_rx.search(text)
    if not m:
        return ""
    return text[m.end():m.end() + length].strip()


def extract_executive_overview(text: str, length: int = 3000) -> str:
    """Verbatim block after the first 'Situation overview' / 'Global
    epidemiological update' header (best of three candidate anchors)."""
    for rx in SITUATION_OVERVIEW_HEADERS:
        chunk = _slice_after(text, rx, length)
        if chunk:
            return chunk
    return ""


def extract_recommendations_text(text: str, length: int = 4000) -> str:
    for rx in RECOMMENDATIONS_HEADERS:
        chunk = _slice_after(text, rx, length)
        if chunk:
            return chunk
    return ""


def extract_outlook_text(text: str, length: int = 2500) -> str:
    for rx in OUTLOOK_HEADERS:
        chunk = _slice_after(text, rx, length)
        if chunk:
            return chunk
    # Fallback: capture sentences containing "expected"/"likely"/"coming months"
    out: list[str] = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"\b(expected|likely|in\s+the\s+coming|outlook)\b", sent, re.I):
            out.append(sent.strip())
        if len(out) >= 6:
            break
    return " ".join(out)


# Sentence-level driver / risk extractions.
DRIVER_TRIGGERS = re.compile(
    r"\b(due\s+to|driven\s+by|factors?\s+(?:include|such\s+as)|intensified\s+by|exacerbated\s+by|fueled\s+by|attributed\s+to)\b",
    re.I,
)
RISK_TRIGGERS = re.compile(
    r"\b(risk\s+of\s+further\s+spread|high\s+risk|very\s+high\s+risk|risk\s+remains|remains\s+(?:very\s+)?high|continued\s+risk|risk\s+of\s+regional\s+spread)\b",
    re.I,
)


def _split_sentences(text: str) -> list[str]:
    # Crude but adequate. Avoid splitting on "U.S." etc.
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text)
    return [p.strip() for p in parts if p.strip()]


def extract_key_driver_sentences(text: str, limit: int = 10) -> list[str]:
    sents = _split_sentences(text)
    out: list[str] = []
    for s in sents:
        if DRIVER_TRIGGERS.search(s) and 30 < len(s) < 600:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def extract_risk_sentences(text: str, limit: int = 8) -> list[str]:
    sents = _split_sentences(text)
    out: list[str] = []
    for s in sents:
        if RISK_TRIGGERS.search(s) and 30 < len(s) < 600:
            out.append(s)
        if len(out) >= limit:
            break
    return out


# ---------- main driver -------------------------------------------------

def parse_sitrep(path: Path) -> dict:
    raw = read_pdf_text(path)
    text = normalize(raw)

    cum_cases, cum_deaths = extract_cumulative_cases_deaths(text)
    cfr = extract_cfr_pct(text)
    mom_signed, mom_direction = extract_mom_change(text)
    risk = extract_global_risk(text)
    pop_risk = extract_population_at_risk(text)
    countries = extract_countries_reporting(text)
    regions = extract_regions_with_outbreak(text)
    breakdown = extract_regional_breakdown(text)

    return {
        # Atomic numeric / categorical fields (drive the cumulative timeseries CSV)
        "global_risk_level":         risk,
        "total_cases_ytd":           cum_cases,
        "total_deaths_ytd":          cum_deaths,
        "cfr_pct":                   cfr,
        "mom_change_pct":            mom_signed,        # signed: +5 means increase
        "mom_direction":             mom_direction,     # 'increase' | 'decrease' | None
        "population_at_risk":        pop_risk,
        "countries_reporting_count": countries,
        "regions_with_outbreak":     regions,
        "regional_breakdown":        breakdown,

        # Verbatim analytical text blocks (for Hard-tier GT references)
        "executive_overview_text":   extract_executive_overview(text),
        "recommendations_text":      extract_recommendations_text(text),
        "outlook_text":              extract_outlook_text(text),
        "key_drivers_sentences":     extract_key_driver_sentences(text),
        "risk_sentences":            extract_risk_sentences(text),
    }
