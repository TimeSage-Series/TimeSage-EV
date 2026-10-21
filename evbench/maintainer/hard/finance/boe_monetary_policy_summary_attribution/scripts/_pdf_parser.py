"""Parse a Bank of England Monetary Policy Summary and Minutes PDF into
structured Hard-tier fields.

BoE PDFs follow a recurring layout (since the post-2015 'one voice' format):

  * Page 1 header: 'Monetary Policy Summary, <month> <year>'
  * First paragraph: vote tally and Bank Rate decision, in the canonical
    form "At its meeting ending on <DD month YYYY>, the MPC voted by a
    majority of N-N to <maintain|increase|reduce> Bank Rate (by 0.NN
    percentage points,) to N.NN%."
  * Subsequent paragraphs ('The Committee has a remit ...' / 'The economy
    has...') give the inflation assessment, growth/labor market context,
    and forward guidance.
  * 'Minutes of the Monetary Policy Committee meeting...' begins later in
    the document with much longer paragraphs on inflation drivers, labour
    market, growth, and risks (upside / downside).

The parser is regex/keyword-driven against the raw extracted text. PDF
text extraction order is mostly stable issue-to-issue; where layout breaks
an extraction we fall back to a wider character window. All extractions
are best-effort and recorded verbatim in ``gt_evidence.md`` so the LLM
judge can verify against the source.
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
    # BoE PDFs sometimes break sentences mid-line; merge inside paragraphs.
    t = re.sub(r"-\n", "", t)
    return t


# ---------- decision + vote + rate --------------------------------------

# Headline decision sentence. Covers the canonical phrasings:
#   'voted by a majority of 7-2 to maintain Bank Rate at 5.25%'
#   'voted by a majority of 6-3 to reduce Bank Rate by 0.25 percentage points, to 4.75%'
#   'voted by a majority of 7-2 to increase Bank Rate by 0.5 percentage points, to 5%'
#   'voted unanimously to maintain Bank Rate at 4%'
HEADLINE_DECISION_RX = re.compile(
    r"voted\s+(?:by\s+a\s+majority\s+of\s+(\d+)\s*[-–]\s*(\d+)|unanimously)\s+"
    r"to\s+(maintain|increase|reduce|cut|raise|lower)\s+Bank\s+Rate"
    r"(?:\s+by\s+(\d+(?:\.\d+)?)\s+percentage\s+point[s]?)?"
    r"(?:\s*,?\s*to\s+(\d+(?:\.\d+)?)\s*%|\s+at\s+(\d+(?:\.\d+)?)\s*%)",
    re.IGNORECASE | re.DOTALL,
)

# Looser fallback that finds 'Bank Rate at N.NN%' near the top of the document.
RATE_FALLBACK_RX = re.compile(r"Bank\s+Rate\s+(?:at|to)\s+(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)


def _decision_enum(verb: str, pct_change: float | None) -> str:
    """Map (verb, magnitude) to the answer-schema enum value."""
    v = verb.lower()
    if v in ("maintain",):
        return "hold"
    if v in ("reduce", "cut", "lower"):
        if pct_change is not None:
            if abs(pct_change - 0.50) < 1e-6: return "cut_50bp"
            if abs(pct_change - 0.25) < 1e-6: return "cut_25bp"
        return "other"
    if v in ("increase", "raise"):
        if pct_change is not None:
            if abs(pct_change - 0.50) < 1e-6: return "hike_50bp"
            if abs(pct_change - 0.25) < 1e-6: return "hike_25bp"
        return "other"
    return "other"


def extract_headline_decision(text: str) -> dict:
    """Return decision enum, vote string, magnitude, and ending rate.

    The first headline match is preferred (the Summary opening sentence);
    later occurrences in the minutes are duplicates of the same phrasing.
    """
    out: dict = {
        "bank_rate_decision": None,
        "mpc_vote": None,
        "pct_change": None,
        "current_bank_rate_pct": None,
    }
    m = HEADLINE_DECISION_RX.search(text)
    if m:
        a, b, verb, mag, to_pct, at_pct = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)
        if a and b:
            vote = f"{a}-{b} for {verb.lower()}"
        else:
            vote = f"unanimous for {verb.lower()}"
        out["mpc_vote"] = vote
        out["pct_change"] = float(mag) if mag else None
        # ending rate: prefer 'to N%' (for changes) else 'at N%' (for holds)
        end_pct = to_pct or at_pct
        if end_pct:
            try: out["current_bank_rate_pct"] = float(end_pct)
            except ValueError: pass
        out["bank_rate_decision"] = _decision_enum(verb, out["pct_change"])

    if out["current_bank_rate_pct"] is None:
        m2 = RATE_FALLBACK_RX.search(text)
        if m2:
            try: out["current_bank_rate_pct"] = float(m2.group(1))
            except ValueError: pass

    return out


# ---------- analytical (Hard-tier) extracted text -----------------------

# Section markers we anchor extraction on.
SUMMARY_HEADERS = [
    re.compile(r"(?i)Monetary\s+Policy\s+Summary"),
]
INFLATION_HEADERS = [
    re.compile(r"(?i)\bConsumer\s+price\s+inflation\b"),
    re.compile(r"(?i)\bCPI\s+inflation\b"),
    re.compile(r"(?i)\bInflation\s+(?:has|is|remains|was|developments)\b"),
]
GROWTH_LABOUR_HEADERS = [
    re.compile(r"(?i)\b(GDP|output)\s+(?:growth|has|is|was)\b"),
    re.compile(r"(?i)\bUK\s+GDP\b"),
    re.compile(r"(?i)\blabour\s+market\b"),
    re.compile(r"(?i)\bemployment\s+growth\b"),
]
RISK_HEADERS = [
    re.compile(r"(?i)\b(?:upside|downside)\s+risks?\b"),
    re.compile(r"(?i)\brisks?\s+(?:remain|are|to\s+inflation|to\s+the\s+outlook)\b"),
]
OUTLOOK_HEADERS = [
    re.compile(r"(?i)\bMonetary\s+policy\s+will\s+need\s+to\b"),
    re.compile(r"(?i)\bThe\s+Committee\s+continues\s+to\s+judge\b"),
    re.compile(r"(?i)\bgradual\s+and\s+careful\b"),
    re.compile(r"(?i)\brestrictive\s+for\s+(?:an\s+)?(?:extended|sufficiently)\b"),
    re.compile(r"(?i)\boutlook\s+for\s+(?:UK\s+)?(?:inflation|the\s+economy)\b"),
]


def _slice_after(text: str, header_rx: re.Pattern, length: int) -> str:
    m = header_rx.search(text)
    if not m: return ""
    return text[m.end():m.end() + length].strip()


def extract_executive_overview(text: str, length: int = 2500) -> str:
    """Verbatim block after the 'Monetary Policy Summary' header (first page)."""
    for rx in SUMMARY_HEADERS:
        chunk = _slice_after(text, rx, length)
        if chunk: return chunk
    # Fallback: first ~2500 chars of the document.
    return text[:length].strip()


def extract_inflation_assessment(text: str, length: int = 1500) -> str:
    for rx in INFLATION_HEADERS:
        chunk = _slice_after(text, rx, length)
        if chunk and len(chunk) > 80: return chunk
    # Fallback: sentences mentioning CPI or 2% target.
    sents = _split_sentences(text)
    out = [s for s in sents if re.search(r"(CPI|consumer\s+price\s+inflation|2\s*%\s+target|services\s+inflation|core\s+inflation)", s, re.I)]
    return " ".join(out[:8])


def extract_growth_labour_assessment(text: str, length: int = 1500) -> str:
    chunks = []
    for rx in GROWTH_LABOUR_HEADERS:
        chunk = _slice_after(text, rx, length)
        if chunk: chunks.append(chunk)
    if chunks:
        # Pick the longest contiguous block (likely the main paragraph).
        return max(chunks, key=len)
    sents = _split_sentences(text)
    out = [s for s in sents if re.search(r"(GDP|labour\s+market|employment|unemployment|wage|pay)", s, re.I)]
    return " ".join(out[:8])


def extract_risks_text(text: str, length: int = 1500) -> str:
    # Concatenate matches for upside / downside risks language.
    chunks = []
    for rx in RISK_HEADERS:
        for m in rx.finditer(text):
            start = max(0, m.start() - 50)
            end = min(len(text), m.end() + 400)
            chunks.append(text[start:end].strip())
        if len("\n".join(chunks)) > length: break
    return "\n\n".join(chunks[:6])


def extract_outlook_text(text: str, length: int = 1500) -> str:
    chunks = []
    for rx in OUTLOOK_HEADERS:
        for m in rx.finditer(text):
            start = max(0, m.start() - 100)
            end = min(len(text), m.end() + 600)
            chunks.append(text[start:end].strip())
    if not chunks:
        sents = _split_sentences(text)
        chunks = [s for s in sents if re.search(r"\b(restrictive|gradual|careful|continue\s+to\s+monitor|further\s+(progress|easing)|judge\s+that|going\s+forward)\b", s, re.I)]
        return " ".join(chunks[:6])
    return "\n\n".join(chunks[:6])


# ---------- driver sentences --------------------------------------------

DRIVER_TRIGGERS = re.compile(
    r"\b(due\s+to|driven\s+by|reflect(?:ing|s)?|primarily\s+(?:reflect|driven)|"
    r"on\s+account\s+of|owing\s+to|attributable\s+to|underpinned\s+by|"
    r"factors?\s+(?:include|such\s+as))\b",
    re.IGNORECASE,
)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text)
    return [p.strip() for p in parts if p.strip()]


def extract_key_driver_sentences(text: str, limit: int = 12) -> list[str]:
    sents = _split_sentences(text)
    out: list[str] = []
    for s in sents:
        if DRIVER_TRIGGERS.search(s) and 40 < len(s) < 600:
            out.append(s)
        if len(out) >= limit: break
    return out


# ---------- main driver -------------------------------------------------

def parse_summary(path: Path) -> dict:
    raw = read_pdf_text(path)
    text = normalize(raw)

    decision = extract_headline_decision(text)

    return {
        # Atomic numeric / categorical fields (drive the cumulative TS).
        "bank_rate_decision":          decision["bank_rate_decision"],
        "current_bank_rate_pct":       decision["current_bank_rate_pct"],
        "mpc_vote":                    decision["mpc_vote"],
        "pct_change":                  decision["pct_change"],

        # Verbatim analytical text blocks (for Hard-tier GT references).
        "executive_overview_text":     extract_executive_overview(text),
        "inflation_assessment_text":   extract_inflation_assessment(text),
        "growth_labor_assessment_text":extract_growth_labour_assessment(text),
        "risks_text":                  extract_risks_text(text),
        "outlook_text":                extract_outlook_text(text),
        "key_drivers_sentences":       extract_key_driver_sentences(text),
    }
