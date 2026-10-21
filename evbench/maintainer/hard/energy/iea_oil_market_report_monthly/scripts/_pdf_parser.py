"""Parse an IEA Oil Market Report (OMR) Highlights PDF into Hard-tier fields.

The free version of the OMR is a Highlights document (~10-15 pages). It opens
with a one-page "Highlights" bullet list that summarizes the current month's
demand, supply, OECD stocks, prices and refining commentary. The remaining
pages expand on each topic with narrative drivers, risks, and a forward
12-month outlook.

We extract:

Numeric (used by the cumulative timeseries.csv):
  - global_demand_mbd_latest       — global oil demand, mb/d (most recently
                                     stated full-year or latest-month figure)
  - global_supply_mbd_latest       — world oil supply, mb/d
  - oecd_stocks_million_bbl        — OECD industry inventories, million bbl

Narrative (used by the Hard-tier GT free-text fields):
  - key_drivers_text       — sentences containing 'due to' / 'driven by' /
                             'reflecting' / 'amid'
  - risks_text             — paragraphs/sentences with 'risk' / 'concern' /
                             'uncertainty' / 'headwind'
  - outlook_text           — paragraphs with 'expected' / 'forecast' /
                             'in the coming months' / 'project'
  - highlights_summary_text — verbatim Highlights bullets (page 1)

All extractors are best-effort. The LLM judge has access to the verbatim PDF
at scoring time so small extraction misses are recoverable.
"""
from __future__ import annotations
import re
from pathlib import Path

from pypdf import PdfReader


# ---------- core text extraction ----------------------------------------

def read_pdf_text(path: Path) -> str:
    r = PdfReader(str(path))
    return "\n".join(p.extract_text() or "" for p in r.pages)


def read_pdf_pages(path: Path) -> list[str]:
    r = PdfReader(str(path))
    return [p.extract_text() or "" for p in r.pages]


_NBSP = re.compile(r"[     ]")
_MULTISPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    t = _NBSP.sub(" ", text)
    t = t.replace("‐", "-").replace("‑", "-")
    t = _MULTISPACE.sub(" ", t)
    t = _MULTI_NEWLINE.sub("\n\n", t)
    return t


def _flatten(text: str) -> str:
    """Single-line normalization used only for numeric regex extraction.

    PDF rendering frequently splits long numbers across lines or inserts
    a stray space inside the digits ('10 2.9 mb/d'). Collapsing whitespace
    to a single space and then re-joining digit-space-digit pairs that are
    immediately followed by an mb/d or $/bbl unit handles these cases
    without distorting unrelated number tokens.
    """
    t = re.sub(r"\s+", " ", text)
    t = re.sub(r"(\d)\s+(\d{1,3}(?:\.\d{1,2})?\s*mb/d)", r"\1\2", t)
    t = re.sub(r"(\d)\s+(\d{1,3}(?:\.\d{1,2})?\s*/?\s*bbl)", r"\1\2", t)
    return t


# ---------- highlights bullets (page 1) ---------------------------------

def extract_highlights_text(pages: list[str], max_chars: int = 4000) -> str:
    """Return the verbatim Highlights bullet list from page 1.

    The OMR Highlights document opens with the word 'Highlights' near the
    top of page 1 followed by 4-7 short bullet paragraphs. We slice from the
    first 'Highlights' header to the end of page 1 (or page 2 if page 1 is
    short).
    """
    if not pages:
        return ""
    p1 = pages[0]
    m = re.search(r"\bHighlights\b", p1, re.I)
    block = p1[m.start():] if m else p1
    # If page 1 cuts off the highlights list, append a portion of page 2.
    if len(block) < 800 and len(pages) > 1:
        block = block + "\n" + pages[1][:2000]
    return normalize(block)[:max_chars].strip()


# ---------- numeric extraction (supply level + Brent spot) --------------

# Each OMR Highlights bullet quotes the latest monthly oil supply LEVEL in
# the form "... to NN.N mb/d [in Month]" (every recent issue uses this).
# Brent spot is similarly quoted as "$NN/bbl" within the prices bullet.
# Earlier extractors targeted demand level and OECD stocks too, but those
# phrases vary too much (often quoted as growth or 5-year deviations) to
# extract reliably — supply level and Brent are the two robust signals.

_SUPPLY_LEVEL_RX = re.compile(
    r"(?:world|global)\s+(?:oil\s+)?(?:supply|production)"
    r".{0,300}?\bto\s+(?:a\s+record\s+|around\s+|nearly\s+|just\s+|almost\s+)?"
    r"(\d{2,3}(?:\.\d{1,2})?)\s*mb/d",
    re.IGNORECASE | re.DOTALL,
)
_BBL_PRICE_RX = re.compile(r"\$\s*(\d{2,3}(?:\.\d{1,2})?)\s*/?\s*bbl", re.I)


def extract_global_supply_mbd(highlights: str) -> float | None:
    """Return the latest global oil supply level (mb/d) from the supply
    bullet's 'to NN.N mb/d' phrase. Search is confined to `highlights` so
    that forward-year forecasts from the body don't get picked up as the
    latest value. Returns None if no plausible match."""
    flat = _flatten(highlights)
    for m in _SUPPLY_LEVEL_RX.finditer(flat):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        if 70.0 <= v <= 130.0:
            return v
    return None


def extract_brent_spot_usd_bbl(highlights: str, full_text: str) -> float | None:
    """Return a plausible Brent spot price ($/bbl) quoted in the Highlights
    bullets. Looks near 'Brent' or 'North Sea Dated' (the OMR sometimes
    cites the latter as the spot benchmark when discussing physical prices).

    Search is confined to `highlights` to avoid stray $/bbl figures from
    the body's spread / CFD / margin tables. Returns None if no plausible
    match — the LLM judge can fall back to the verbatim Highlights text.
    """
    flat = _flatten(highlights)
    anchors = list(re.finditer(r"\b(?:Brent|North\s+Sea\s+Dated)\b", flat, re.I))
    for bm in anchors:
        chunk = flat[bm.start(): bm.start() + 400]
        for pm in _BBL_PRICE_RX.finditer(chunk):
            try:
                v = float(pm.group(1))
            except ValueError:
                continue
            if 30.0 <= v <= 200.0:
                return v
    return None


# ---------- driver / risk / outlook sentence extraction -----------------

DRIVER_TRIGGERS = re.compile(
    r"\b(driven\s+by|due\s+to|amid|reflecting|owing\s+to|on\s+the\s+back\s+of|"
    r"on\s+account\s+of|as\s+a\s+result\s+of|stemming\s+from|because\s+of|"
    r"thanks\s+to|fueled\s+by|attributed\s+to|boosted\s+by|underpinned\s+by)\b",
    re.I,
)

RISK_TRIGGERS = re.compile(
    r"\b(uncertain(?:ty|ties)?|risks?|concerns?|headwinds?|downside|fragile|"
    r"volatility|cautious(?:ly)?|tensions?|geopolitical)\b",
    re.I,
)

OUTLOOK_TRIGGERS = re.compile(
    r"\b(expected|expectations?|anticipate(?:d)?|forecast(?:ed|s)?|projected|"
    r"set\s+to|in\s+the\s+coming\s+(?:months|year|quarter)|near[-\s]term\s+outlook|"
    r"looking\s+ahead|outlook|next\s+year|in\s+202[4-9])\b",
    re.I,
)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\"\$])", text)
    return [p.strip() for p in parts if p.strip()]


def _scan(text: str, trigger: re.Pattern, limit: int,
          min_len: int = 30, max_len: int = 600) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in _split_sentences(text):
        if trigger.search(s) and min_len < len(s) < max_len:
            key = s[:120]
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
        if len(out) >= limit:
            break
    return out


def extract_key_drivers_sentences(text: str, limit: int = 12) -> list[str]:
    return _scan(text, DRIVER_TRIGGERS, limit)


def extract_risks_sentences(text: str, limit: int = 10) -> list[str]:
    return _scan(text, RISK_TRIGGERS, limit)


def extract_outlook_sentences(text: str, limit: int = 10) -> list[str]:
    return _scan(text, OUTLOOK_TRIGGERS, limit)


# ---------- balance signal classifier (next-issue dual-GT) --------------

# The Hard-tier outlook field 'expected_oil_market_balance' is classified
# {tightening, balanced, surplus, unclear}. The CURRENT issue's classifier
# is a keyword-count heuristic over the Highlights + first 3 pages of the
# narrative. The NEXT issue's classification serves as the dual-GT target
# at scoring time.

_TIGHTEN_RX = re.compile(
    r"\b(tighten(?:ing)?|deficit|stock\s+draw|inventor(?:y|ies)\s+(?:draw|fell|drew)|"
    r"supply\s+(?:short|shortfall|outage|disrupt)|undersuppl|backwardation|"
    r"undersupplied)\b", re.I,
)
_SURPLUS_RX = re.compile(
    r"\b(surplus|overhang|stock\s+build|inventor(?:y|ies)\s+(?:build|rose|increased)|"
    r"oversuppl|contango|excess\s+(?:supply|stocks)|overhang|stocks\s+built|"
    r"build\s+in\s+(?:global|world|oecd)\s+stocks)\b", re.I,
)
_BALANCED_RX = re.compile(
    r"\b(balanced|broadly\s+balanced|in\s+line\s+with|roughly\s+matched|"
    r"largely\s+balanced)\b", re.I,
)


def classify_balance_signal(text: str) -> str:
    """Return one of {tightening, balanced, surplus, unclear} by counting
    keyword hits in the first ~6000 chars (Highlights + narrative opening).
    """
    head = text[:6000]
    n_t = len(_TIGHTEN_RX.findall(head))
    n_s = len(_SURPLUS_RX.findall(head))
    n_b = len(_BALANCED_RX.findall(head))
    counts = {"tightening": n_t, "surplus": n_s, "balanced": n_b}
    if max(counts.values()) == 0:
        return "unclear"
    # If surplus & tightening are both materially present without a clear
    # majority, prefer 'balanced' if it has any hit, else the larger count.
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top, top_count = ranked[0]
    second, second_count = ranked[1]
    if top_count == second_count:
        if n_b > 0:
            return "balanced"
        return "unclear"
    return top


# ---------- main driver -------------------------------------------------

def parse_omr(path: Path) -> dict:
    pages = read_pdf_pages(path)
    raw = "\n".join(pages)
    text = normalize(raw)

    highlights = extract_highlights_text(pages)

    supply = extract_global_supply_mbd(highlights)
    brent_usd_bbl = extract_brent_spot_usd_bbl(highlights, text)

    drivers = extract_key_drivers_sentences(text)
    risks = extract_risks_sentences(text)
    outlook = extract_outlook_sentences(text)

    balance_signal = classify_balance_signal(text)

    return {
        # Atomic numeric fields (cumulative TS). Two robust series:
        # supply LEVEL (mb/d, from the supply bullet's 'to NN.N mb/d') and
        # Brent spot price ($/bbl, quoted near 'Brent' in the prices bullet).
        "global_supply_mbd_latest":   supply,
        "brent_spot_price_usd_bbl":   brent_usd_bbl,

        # Classified market-balance signal — NOT staged into timeseries.csv
        # (it leaks the analytical answer to the agent). Used internally as
        # the dual-GT target via the NEXT issue's classification.
        "market_balance_signal_keyword": balance_signal,

        # Verbatim narrative text blocks for Hard-tier GT references.
        "highlights_summary_text":    highlights,

        # Sentence-level analytical extracts.
        "key_drivers_sentences":      drivers,
        "risks_sentences":            risks,
        "outlook_sentences":          outlook,
    }
