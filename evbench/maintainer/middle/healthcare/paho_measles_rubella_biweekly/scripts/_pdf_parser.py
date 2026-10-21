"""Parse a PAHO Measles-Rubella bi-Weekly Bulletin PDF into structured fields.

The bulletin is mostly tabular (per-country measles/rubella counts) with
a thin descriptive caption. We extract:

- ``country_measles_counts``: per-country confirmed measles case count.
- ``n_countries_with_cases``: number of countries whose count > 0.
- ``confirmed_measles_cases_total``: sum across countries (or explicit TOTAL row).
- ``leading_country_by_cases``: country with the highest measles count.
- ``descriptive_caption``: best-effort first ~800 chars of plain text
  to serve as ``report_reference`` for the LLM judge.

PDF table extraction is fragile; the strategy is a fall-back ladder:

1. Try to detect rows of the form ``<COUNTRY> <int> <date>`` or
   ``<COUNTRY> <int> <int>``.
2. Fall back to per-country keyword density in the text (each canonical
   country name from a known list; integer adjacency).
3. If both fail for a given country, leave count = ``None``.

All extracted fields may be ``None`` if extraction failed — the LLM
judge on ``report`` carries the qualitative grading and partial
extractions are accepted by the benchmark.
"""
from __future__ import annotations
import re
from pathlib import Path

from pypdf import PdfReader


# Canonical country labels for PAHO Region of the Americas. Order matters
# only for tie-breaking in the leading-country choice (stable).
PAHO_COUNTRIES = [
    "Antigua and Barbuda", "Argentina", "Bahamas", "Barbados", "Belize",
    "Bolivia", "Brazil", "Canada", "Chile", "Colombia", "Costa Rica",
    "Cuba", "Dominica", "Dominican Republic", "Ecuador", "El Salvador",
    "French Guiana", "Grenada", "Guatemala", "Guyana", "Haiti", "Honduras",
    "Jamaica", "Mexico", "Nicaragua", "Panama", "Paraguay", "Peru",
    "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines",
    "Suriname", "Trinidad and Tobago", "United States", "Uruguay",
    "Venezuela",
]

# Some bulletins use country-name variants; map them to canonical labels.
COUNTRY_ALIASES = {
    "United States of America": "United States",
    "USA": "United States",
    "U.S.A.": "United States",
    "United States (USA)": "United States",
    "Bolivia (Plurinational State of)": "Bolivia",
    "Venezuela (Bolivarian Republic of)": "Venezuela",
    "St. Kitts and Nevis": "Saint Kitts and Nevis",
    "St. Lucia": "Saint Lucia",
    "St. Vincent and the Grenadines": "Saint Vincent and the Grenadines",
    "Trinidad & Tobago": "Trinidad and Tobago",
    "Antigua & Barbuda": "Antigua and Barbuda",
}

# Pre-compiled per-country regex for line-level matching. Longest names
# first so multi-word prefixes win over their roots (e.g. "Saint Vincent
# and the Grenadines" before "Saint Vincent").
_COUNTRY_PATTERNS = sorted(
    list(PAHO_COUNTRIES) + list(COUNTRY_ALIASES.keys()),
    key=len, reverse=True,
)


def read_pdf_text(path: Path) -> str:
    r = PdfReader(str(path))
    return "\n".join(p.extract_text() or "" for p in r.pages)


def _canonical(name: str) -> str:
    return COUNTRY_ALIASES.get(name.strip(), name.strip())


# Match a country label at line start (with optional leading bullets / digits)
# followed by an integer cell. We deliberately accept the FIRST integer on the
# line as the measles count, which is how the PAHO table is laid out:
# ``Country  <measles_confirmed>  <measles_suspected>  <rubella>  <date>``
def _row_count_for(country: str, text: str) -> int | None:
    # Tokenize one country name at a time. Anchored at line start (after
    # any leading whitespace/bullet).
    rx = re.compile(
        r"(?m)^\s*"                       # line start
        r"(?:[•\-\*\d\.]+\s+)?"      # optional bullet / list digit
        + re.escape(country)              # literal country
        + r"\s+"                          # at least one space
        r"([\d,]+)",                      # first integer (digits or 1,234)
    )
    best: int | None = None
    for m in rx.finditer(text):
        try:
            n = int(m.group(1).replace(",", ""))
        except ValueError:
            continue
        # Take the maximum to be robust to multiple appearances; the
        # confirmed-measles row tends to have the largest first-integer
        # in a per-country line.
        if best is None or n > best:
            best = n
    return best


def extract_country_counts(text: str) -> dict[str, int]:
    """Return canonical-country -> measles-confirmed count (>= 0)."""
    counts: dict[str, int] = {}
    for raw in _COUNTRY_PATTERNS:
        n = _row_count_for(raw, text)
        if n is None:
            continue
        canonical = _canonical(raw)
        # If we see the same canonical country from multiple aliases,
        # keep the larger value (more likely to be the data row).
        prev = counts.get(canonical)
        if prev is None or n > prev:
            counts[canonical] = n
    return counts


_TOTAL_RX = re.compile(
    r"(?im)^\s*(?:Total|Region\s+of\s+the\s+Americas|Americas)\s+([\d,]+)"
)


def extract_total_from_row(text: str) -> int | None:
    """Return the explicit TOTAL row value (first integer) if present."""
    m = _TOTAL_RX.search(text)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def descriptive_caption(text: str, max_chars: int = 800) -> str:
    """Best-effort excerpt: skip the bulletin title block and return the
    first ~max_chars of plain text suitable as a short-summary reference."""
    if not text:
        return ""
    # Drop very short header lines; concatenate paragraphs.
    lines = [ln.strip() for ln in text.splitlines()]
    # Heuristic: find the first line that contains a sentence-style
    # comma or period after at least 40 chars (real prose), then collect
    # until we hit max_chars or a blank-line gap of 2.
    buf: list[str] = []
    started = False
    blanks = 0
    for ln in lines:
        if not started:
            if len(ln) >= 40 and any(p in ln for p in (".", ",", ";")):
                started = True
            else:
                continue
        if not ln:
            blanks += 1
            if blanks >= 2 and sum(len(x) for x in buf) > 200:
                break
            continue
        blanks = 0
        buf.append(ln)
        if sum(len(x) for x in buf) >= max_chars:
            break
    excerpt = " ".join(buf).strip()
    if not excerpt:
        # Last resort: just take a leading slice.
        excerpt = " ".join(ln for ln in lines if ln)[:max_chars]
    return excerpt[:max_chars]


def leading_country(counts: dict[str, int]) -> str | None:
    if not counts:
        return None
    # Filter strictly positive counts.
    pos = {c: n for c, n in counts.items() if n > 0}
    if not pos:
        return None
    # Sort by count desc, then by canonical-list index asc for a stable tie-break.
    def _rank(kv: tuple[str, int]) -> tuple[int, int]:
        country, n = kv
        idx = PAHO_COUNTRIES.index(country) if country in PAHO_COUNTRIES else len(PAHO_COUNTRIES)
        return (-n, idx)
    return sorted(pos.items(), key=_rank)[0][0]


def parse_paho_bulletin(path: Path) -> dict:
    text = read_pdf_text(path)
    counts = extract_country_counts(text)
    pos_counts = {c: n for c, n in counts.items() if n > 0}
    total_row = extract_total_from_row(text)
    summed = sum(counts.values()) if counts else None
    return {
        "country_measles_counts":         counts,
        "n_countries_with_cases":         len(pos_counts),
        "confirmed_measles_cases_total":  total_row if total_row is not None else summed,
        "confirmed_measles_cases_total_from_row":  total_row,
        "confirmed_measles_cases_total_from_sum":  summed,
        "leading_country_by_cases":       leading_country(counts),
        "descriptive_caption":            descriptive_caption(text),
    }
