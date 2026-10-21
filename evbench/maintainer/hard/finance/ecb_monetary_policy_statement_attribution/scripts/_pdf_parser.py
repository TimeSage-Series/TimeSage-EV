"""Parse an ECB Combined Monetary Policy Decisions and Statement PDF
into structured Hard-tier fields.

The Combined statement follows a recurring section structure:
  1. Opening paragraph — names the rate decision verbatim:
       "decided to keep the three key ECB interest rates unchanged",
       "decided to lower the three key ECB interest rates by 25 basis points",
       "decided to raise the three key ECB interest rates by 25 basis points".
  2. Rate level paragraph — restates the new deposit-facility / main-
     refinancing / marginal-lending rates ("decreased to 2.00%, 2.15% and
     2.40% respectively" or "remain unchanged at 2.00%, 2.15% and 2.40%").
  3. 'Economic activity' or growth assessment block.
  4. 'Inflation' assessment block.
  5. 'Risk assessment' block (sub-blocks 'Risks to economic growth',
     'Risks to inflation').
  6. 'Monetary and financial conditions' block.
  7. 'Conclusion' / forward guidance block.

The parser is regex/keyword-driven against the extracted text. The Combined
statement layout is stable across meetings; minor variations are absorbed
by fallback patterns. All free-text blocks are kept verbatim so the LLM
judge can verify reasoning against the source.
"""
from __future__ import annotations
import re
from pathlib import Path

from pypdf import PdfReader


# ---------- core text extraction ----------------------------------------

def read_pdf_text(path: Path) -> str:
    r = PdfReader(str(path))
    return "\n".join(p.extract_text() or "" for p in r.pages)


_NBSP = re.compile(r"[    ]")
_MULTISPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    t = _NBSP.sub(" ", text)
    t = _MULTISPACE.sub(" ", t)
    t = _MULTI_NEWLINE.sub("\n\n", t)
    return t


# ---------- atomic categorical / numeric fields -------------------------

# Rate decision phrasings, ordered most-specific first.
RATE_DECISION_PATTERNS = [
    (re.compile(r"decided\s+to\s+lower\s+the\s+three\s+key\s+ECB\s+interest\s+rates\s+by\s+50\s+basis\s+points", re.I), "cut_50bp"),
    (re.compile(r"decided\s+to\s+lower\s+the\s+three\s+key\s+ECB\s+interest\s+rates\s+by\s+25\s+basis\s+points", re.I), "cut_25bp"),
    (re.compile(r"decided\s+to\s+lower\s+the\s+(?:deposit\s+facility\s+rate|three\s+key\s+ECB\s+interest\s+rates)[^.]*?by\s+(\d+)\s+basis\s+points", re.I), "cut_other"),
    (re.compile(r"decided\s+to\s+raise\s+the\s+three\s+key\s+ECB\s+interest\s+rates\s+by\s+50\s+basis\s+points", re.I), "hike_50bp"),
    (re.compile(r"decided\s+to\s+raise\s+the\s+three\s+key\s+ECB\s+interest\s+rates\s+by\s+25\s+basis\s+points", re.I), "hike_25bp"),
    (re.compile(r"decided\s+to\s+raise\s+the\s+three\s+key\s+ECB\s+interest\s+rates\s+by\s+(\d+)\s+basis\s+points", re.I), "hike_other"),
    (re.compile(r"decided\s+to\s+keep\s+the\s+three\s+key\s+ECB\s+interest\s+rates\s+unchanged", re.I), "hold"),
    (re.compile(r"keep\s+the\s+three\s+key\s+ECB\s+interest\s+rates\s+unchanged", re.I), "hold"),
]


def extract_rate_decision(text: str) -> str:
    """Return one of: hold, cut_25bp, cut_50bp, hike_25bp, hike_50bp,
    cut_other, hike_other, other."""
    for rx, label in RATE_DECISION_PATTERNS:
        if rx.search(text):
            return label
    return "other"


# "interest rates on the deposit facility, the main refinancing operations
#  and the marginal lending facility were decreased / will be decreased /
#  remain unchanged at 2.00%, 2.15% and 2.40% respectively"
DEPOSIT_RATE_TRIPLE = re.compile(
    r"deposit\s+facility[^.]{0,400}?(\d+\.\d{1,2})\s*%[^.]{0,60}?(\d+\.\d{1,2})\s*%[^.]{0,60}?(\d+\.\d{1,2})\s*%",
    re.I,
)
# Fallback: "deposit facility rate ... at 2.00%"
DEPOSIT_RATE_SINGLE = re.compile(
    r"deposit\s+facility\s+rate[^.]{0,180}?(\d+\.\d{1,2})\s*%",
    re.I,
)
# Anchored sentence with the new rate level after a decision.
NEW_DEPOSIT_LEVEL = re.compile(
    r"(?:decreased|increased|remain(?:ed)?\s+unchanged|stand|stay|stays|kept)\s+(?:to|at)\s+(\d+\.\d{1,2})\s*%",
    re.I,
)


def extract_deposit_facility_rate_pct(text: str) -> float | None:
    """Return the deposit-facility-rate level (percent, as float).

    Strategy: prefer the triple-rate phrasing (which gives the new deposit /
    MRO / marginal-lending levels in that order, so the first capture is the
    deposit rate). Fall back to single-rate and 'remain unchanged at' anchors.
    """
    m = DEPOSIT_RATE_TRIPLE.search(text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m = DEPOSIT_RATE_SINGLE.search(text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    m = NEW_DEPOSIT_LEVEL.search(text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


# ---------- analytical free-text blocks ---------------------------------

# Section headers we anchor extraction off. The Combined statement uses
# bold section titles that the PDF extractor preserves as a separate line.
INFLATION_HEADERS = [
    re.compile(r"(?im)^\s*Inflation\s*$"),
    re.compile(r"(?i)\bInflation\b\s+(?:has|continued|developed|remains|is|fell|rose)"),
]
GROWTH_HEADERS = [
    re.compile(r"(?im)^\s*Economic\s+activity\s*$"),
    re.compile(r"(?im)^\s*Economic\s+growth\s*$"),
    re.compile(r"(?i)\bEconomic\s+activity\b\s+(?:has|continued|developed|remains|grew|grew\s+by|expanded)"),
]
RISK_HEADERS = [
    re.compile(r"(?im)^\s*Risk\s+assessment\s*$"),
    re.compile(r"(?im)^\s*Risks?\s+to\s+(?:economic\s+growth|inflation|the\s+outlook)\s*$"),
    re.compile(r"(?i)\bRisks?\s+to\s+(?:economic\s+growth|inflation|the\s+economic\s+outlook)"),
]
CONCLUSION_HEADERS = [
    re.compile(r"(?im)^\s*Conclusion\s*$"),
    re.compile(r"(?i)\bWe\s+are\s+now\s+ready\s+to\s+take\s+your\s+questions"),
    re.compile(r"(?i)\bThe\s+Governing\s+Council\s+stands\s+ready"),
]


def _slice_after(text: str, header_rx: re.Pattern, length: int) -> str:
    m = header_rx.search(text)
    if not m:
        return ""
    return text[m.end():m.end() + length].strip()


def _slice_between(text: str, start_rx: re.Pattern, stop_rxs: list[re.Pattern], max_length: int) -> str:
    """Take text from the first match of start_rx up to the first stop_rx,
    capped at max_length characters. Returns '' if start_rx is absent."""
    m = start_rx.search(text)
    if not m:
        return ""
    start = m.end()
    end = start + max_length
    for srx in stop_rxs:
        sm = srx.search(text, pos=start)
        if sm and sm.start() < end:
            end = sm.start()
    return text[start:end].strip()


def extract_executive_overview(text: str, length: int = 2000) -> str:
    """Verbatim opening ~2000 chars of the statement body — typically the
    rate-decision paragraph plus the first analytical paragraphs."""
    # Skip leading boilerplate ("PRESS CONFERENCE", date, etc.) and start
    # from the first 'Good afternoon' / 'The Governing Council' anchor.
    anchors = [
        re.compile(r"(?i)Good\s+(?:afternoon|morning)"),
        re.compile(r"(?i)The\s+Governing\s+Council\s+(?:today\s+)?decided"),
        re.compile(r"(?i)Based\s+on\s+(?:our|its)\s+(?:current\s+)?assessment"),
    ]
    for rx in anchors:
        chunk = _slice_after(text, rx, length)
        if chunk:
            return chunk
    return text[:length].strip()


def extract_inflation_assessment(text: str, length: int = 2200) -> str:
    """Verbatim 'Inflation' block."""
    stops = GROWTH_HEADERS + RISK_HEADERS + CONCLUSION_HEADERS
    for rx in INFLATION_HEADERS:
        chunk = _slice_between(text, rx, stops, length)
        if chunk:
            return chunk
    # Fallback: any paragraph containing 'inflation'
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        if re.search(r"\binflation\b", para, re.I) and 80 < len(para) < 1200:
            out.append(para.strip())
        if sum(len(p) for p in out) > length:
            break
    return "\n\n".join(out)


def extract_growth_assessment(text: str, length: int = 2200) -> str:
    """Verbatim 'Economic activity' / growth block."""
    stops = INFLATION_HEADERS + RISK_HEADERS + CONCLUSION_HEADERS
    for rx in GROWTH_HEADERS:
        chunk = _slice_between(text, rx, stops, length)
        if chunk:
            return chunk
    # Fallback: paragraphs with growth/GDP/activity
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        if re.search(r"\b(growth|GDP|activity|economy)\b", para, re.I) and 80 < len(para) < 1200:
            out.append(para.strip())
        if sum(len(p) for p in out) > length:
            break
    return "\n\n".join(out)


def extract_risks_text(text: str, length: int = 2400) -> str:
    """Verbatim 'Risk assessment' block — typically 'Risks to economic
    growth' followed by 'Risks to inflation' sub-blocks."""
    stops = CONCLUSION_HEADERS
    for rx in RISK_HEADERS:
        chunk = _slice_between(text, rx, stops, length)
        if chunk:
            return chunk
    # Fallback: paragraphs containing 'risk(s)' near keywords
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        if re.search(r"\brisks?\b", para, re.I) and 80 < len(para) < 1200:
            out.append(para.strip())
        if sum(len(p) for p in out) > length:
            break
    return "\n\n".join(out)


def extract_outlook_text(text: str, length: int = 1800) -> str:
    """Verbatim conclusion / forward-guidance block. Picks the 'Conclusion'
    header if present; falls back to sentences containing forward-looking
    cues."""
    stops = [re.compile(r"(?i)\bWe\s+are\s+now\s+ready\s+to\s+take\s+your\s+questions")]
    for rx in CONCLUSION_HEADERS:
        chunk = _slice_between(text, rx, stops, length)
        if chunk:
            return chunk
    # Fallback: forward-looking sentences
    out: list[str] = []
    for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text):
        if re.search(r"\b(data-dependent|meeting-by-meeting|going\s+forward|in\s+the\s+coming|expected|outlook|will\s+continue|stands\s+ready)\b", sent, re.I):
            out.append(sent.strip())
        if sum(len(s) for s in out) > length:
            break
    return " ".join(out)


# Driver-sentence extraction — sentences that explicitly attribute the
# current assessment to a cause.
DRIVER_TRIGGERS = re.compile(
    r"\b(due\s+to|driven\s+by|reflecting|reflects|amid|on\s+the\s+back\s+of|as\s+a\s+result\s+of|because\s+of|owing\s+to|factors?\s+(?:include|such\s+as)|attributed\s+to|on\s+account\s+of)\b",
    re.I,
)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text)
    return [p.strip() for p in parts if p.strip()]


def extract_key_driver_sentences(text: str, limit: int = 12) -> list[str]:
    sents = _split_sentences(text)
    out: list[str] = []
    for s in sents:
        if DRIVER_TRIGGERS.search(s) and 30 < len(s) < 700:
            out.append(s)
        if len(out) >= limit:
            break
    return out


# ---------- main driver -------------------------------------------------

def parse_statement(path: Path) -> dict:
    raw = read_pdf_text(path)
    text = normalize(raw)

    return {
        # Atomic categorical / numeric (drive cumulative timeseries CSV)
        "rate_decision":                  extract_rate_decision(text),
        "deposit_facility_rate_pct":      extract_deposit_facility_rate_pct(text),

        # Verbatim analytical blocks (for Hard-tier GT references)
        "executive_overview_text":        extract_executive_overview(text),
        "inflation_assessment_text":      extract_inflation_assessment(text),
        "growth_assessment_text":         extract_growth_assessment(text),
        "risks_text":                     extract_risks_text(text),
        "outlook_text":                   extract_outlook_text(text),
        "key_drivers_sentences":          extract_key_driver_sentences(text),

        # Raw text head (200 chars) for debugging — never used downstream.
        "_raw_head_debug":                text[:200],
    }
