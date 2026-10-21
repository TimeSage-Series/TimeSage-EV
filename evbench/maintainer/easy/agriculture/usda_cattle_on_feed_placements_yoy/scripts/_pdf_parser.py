"""Parse a USDA NASS Cattle on Feed PDF for the Placements YoY headline.

The first page carries the headline paragraph:

    'Placements in feedlots during <Month> totaled <N.NN> million head,
     <X> percent {above|below} <prior YYYY>.'

Some issues use phrasing like 'X percent above 2025.' (no leading 'the')
or 'equal to 2025'. We anchor on the verb {above|below|equal} word.
"""
from __future__ import annotations
import re
from pathlib import Path

from pypdf import PdfReader


_NBSP = re.compile(r"[   ]")
_MS = re.compile(r"[ \t]+")
_NL = re.compile(r"\n{3,}")


def normalize(text: str) -> str:
    t = _NBSP.sub(" ", text)
    t = _MS.sub(" ", t)
    t = _NL.sub("\n\n", t)
    return t


def read_pdf_first_pages(path: Path, n: int = 2) -> str:
    r = PdfReader(str(path))
    return "\n".join(p.extract_text() or "" for p in r.pages[:n])


# 'Placements in feedlots during February totaled 1.61 million head, 4 percent above 2025.'
# 'Placements in feedlots during May totaled 1.66 million head, 5 percent below 2024.'
# 'Placements ... were equal to 2024.'
PLACEMENTS_RX = re.compile(
    r"Placements\s+in\s+feedlots\s+during\s+(?P<month>[A-Z][a-z]+)\s+totaled\s+"
    r"(?P<million>[\d.]+)\s+million\s+head,?\s+"
    r"(?:(?P<pct>[\d.]+)\s+percent\s+)?"
    r"(?P<dir>above|below|equal\s+to)\s+"
    r"(?P<year>20\d{2})",
    re.IGNORECASE,
)


def parse_placements_yoy(text: str) -> dict | None:
    m = PLACEMENTS_RX.search(text)
    if not m:
        return None
    direction_raw = m.group("dir").lower()
    if "above" in direction_raw:
        cls = "above_prior_year"
    elif "below" in direction_raw:
        cls = "below_prior_year"
    else:
        cls = "equal_to_prior_year"
    pct = float(m.group("pct")) if m.group("pct") else 0.0
    return {
        "data_month_name":    m.group("month"),
        "prior_year":         int(m.group("year")),
        "placements_million": float(m.group("million")),
        "yoy_pct_magnitude":  pct,
        "yoy_direction_raw":  direction_raw,
        "placements_yoy_class": cls,
        "verbatim_phrase":    m.group(0).strip(),
    }


def parse_pdf(path: Path) -> dict | None:
    text = normalize(read_pdf_first_pages(path, n=2))
    return parse_placements_yoy(text)
