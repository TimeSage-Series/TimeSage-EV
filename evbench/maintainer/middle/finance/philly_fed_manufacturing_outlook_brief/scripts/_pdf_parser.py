"""Parse Philly Fed MBOS monthly PDF for diffusion indexes + narrative.

The PDF layout (verified against 2024-01..2026-04 issues):
  Page 1:  "<Month> <Year>" header  +  "Release Date: <date>" + narrative
  Page 2:  continuation of narrative ending with "Summary" paragraph
  Page 3:  charts + footnotes (often blank)

Per-month we extract:
  - release_date (string)
  - gac_diffusion_index_current  (numeric: General Activity Conditions)
  - gac_diffusion_index_prev_month  (the "from X.X in <prev_month>" anchor)
  - new_orders_index_current
  - shipments_index_current
  - employment_index_current
  - prices_paid_index_current
  - future_gac_index  (the 6-month-ahead diffusion)
  - summary_verbatim  (the "Summary" closing paragraph)
  - narrative_verbatim  (page-1 first ~2200 chars after header)
  - direction  ({expanding, contracting, mixed})
"""
from __future__ import annotations
import re
from pathlib import Path
from pypdf import PdfReader


_MS = re.compile(r"[ \t]+")
_NL = re.compile(r"\n{3,}")


def read_pages(path: Path) -> list[str]:
    r = PdfReader(str(path))
    return [(p.extract_text() or "") for p in r.pages]


def normalize(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = _MS.sub(" ", text)
    text = _NL.sub("\n\n", text)
    return text.strip()


_RELEASE_RX = re.compile(
    r"Release\s+Date:\s*([A-Z][a-z]+\s+\d{1,2},?\s+20\d{2})", re.I)

# Movement phrasings observed across 28 issues:
#   'rose from 18.1 in March to 26.7 in April'
#   'ticked up from a revised reading of -12.8 in December to -10.6 in January'
#   'jumped from a revised reading of -10.9 in December to 44.3 in January'
#   'remained unchanged at -4.0 in June'
#   'edged up to 40.8'
_VERB_GROUP = (r"(?:rose|fell|increased|decreased|moved|edged|jumped|climbed|"
               r"declined|dropped|ticked\s+up|ticked\s+down|surged|slipped|"
               r"remained\s+unchanged|remained|held)")

_GAC_FROM_TO_RX = re.compile(
    r"diffusion\s+index\s+for\s+current\s+general\s+activity[^.]*?"
    rf"{_VERB_GROUP}\s+(?:up\s+|down\s+|sharply\s+)?"
    r"from\s+(?:a\s+revised\s+reading\s+of\s+)?(-?[\d.]+)[^.]{0,60}?"
    r"to\s+(-?[\d.]+)",
    re.I | re.S,
)
# 'remained unchanged at -4.0' / 'held at 12.6' — only current value
_GAC_AT_RX = re.compile(
    r"diffusion\s+index\s+for\s+current\s+general\s+activity[^.]*?"
    rf"{_VERB_GROUP}\s+(?:unchanged\s+)?at\s+(-?[\d.]+)",
    re.I | re.S,
)
# Bare fallback: any 'to X' / 'at X' after 'general activity'
_GAC_BARE_RX = re.compile(
    r"diffusion\s+index\s+for\s+current\s+general\s+activity[^.]{0,200}?"
    r"\b(?:to|at)\s+(-?[\d.]+)\b",
    re.I | re.S,
)
# 'current shipments index rose 12 points to 34.0'
_SHIPMENTS_RX = re.compile(
    r"current\s+shipments\s+index[^.]*?(?:to|at)\s+(-?[\d.]+)", re.I | re.S)
# 'index for current new orders jumped 24 points to 33.0'
_NEW_ORDERS_RX = re.compile(
    r"current\s+new\s+orders[^.]*?(?:to|at)\s+(-?[\d.]+)", re.I | re.S)
# 'The employment index fell 6 points to -5.1 in April'
_EMPLOY_RX = re.compile(
    r"\bemployment\s+index[^.]*?(?:to|at)\s+(-?[\d.]+)", re.I | re.S)
# 'The prices paid index rose 15 points to 59.3 in April'
_PRICES_PAID_RX = re.compile(
    r"prices\s+paid\s+index[^.]*?(?:to|at)\s+(-?[\d.]+)", re.I | re.S)
# 'future general activity edged up to 40.8'
_FUTURE_GAC_RX = re.compile(
    r"future\s+general\s+activity[^.]*?(?:to|at|index of)\s+(-?[\d.]+)", re.I | re.S)


def _try_float(s):
    try: return float(s)
    except (ValueError, TypeError): return None


def parse_pdf(path: Path) -> dict:
    pages = read_pages(path)
    full = "\n\n".join(normalize(p) for p in pages)
    out: dict = {}

    rm = _RELEASE_RX.search(full)
    out["release_date"] = rm.group(1) if rm else None

    gm = _GAC_FROM_TO_RX.search(full)
    if gm:
        out["gac_diffusion_index_prev_month"] = _try_float(gm.group(1))
        out["gac_diffusion_index_current"]    = _try_float(gm.group(2))
    else:
        at = _GAC_AT_RX.search(full)
        if at:
            out["gac_diffusion_index_prev_month"] = None
            out["gac_diffusion_index_current"]    = _try_float(at.group(1))
        else:
            bm = _GAC_BARE_RX.search(full)
            out["gac_diffusion_index_prev_month"] = None
            out["gac_diffusion_index_current"]    = _try_float(bm.group(1)) if bm else None

    out["new_orders_index_current"]  = _try_float((_NEW_ORDERS_RX.search(full) or [None,None])[1] if _NEW_ORDERS_RX.search(full) else None) \
                                         if False else _try_float((_NEW_ORDERS_RX.search(full).group(1)) if _NEW_ORDERS_RX.search(full) else None)
    out["shipments_index_current"]   = _try_float((_SHIPMENTS_RX.search(full).group(1)) if _SHIPMENTS_RX.search(full) else None)
    out["employment_index_current"]  = _try_float((_EMPLOY_RX.search(full).group(1)) if _EMPLOY_RX.search(full) else None)
    out["prices_paid_index_current"] = _try_float((_PRICES_PAID_RX.search(full).group(1)) if _PRICES_PAID_RX.search(full) else None)
    out["future_gac_index"]          = _try_float((_FUTURE_GAC_RX.search(full).group(1)) if _FUTURE_GAC_RX.search(full) else None)

    # Direction from gac sign
    gac = out["gac_diffusion_index_current"]
    if gac is None:
        out["direction"] = None
    elif gac > 0:
        out["direction"] = "expanding"
    elif gac < 0:
        out["direction"] = "contracting"
    else:
        out["direction"] = "neutral"

    # Verbatim narrative & Summary block
    page1 = pages[0] if pages else ""
    out["narrative_verbatim"] = normalize(page1)[:2400]

    # Summary block: text between "Summary" header and end
    summary_m = re.search(r"\bSummary\b\s*\n+(.*?)(?:\n{2,}|\Z)",
                          "\n\n".join(pages), re.S)
    if summary_m:
        out["summary_verbatim"] = normalize(summary_m.group(1))[:1500]
    else:
        out["summary_verbatim"] = None
    return out
