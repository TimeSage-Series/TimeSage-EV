"""Shared narrative extraction for scenario `format.py` scripts.

Seventeen scenarios append a "narrative block" to their `gt_evidence.md`: a
verbatim excerpt of the source report followed by the sentences that carry
driver / risk / outlook language. That block is what the Faithfulness and
Coverage scorers quote against, so it has to be derived from the source
artifact rather than written by hand.

Two entry points, both imported by `evbench/maintainer/*/*/*/scripts/format.py`:

    src_text, pages = load_source_text(path)
    md = build_narrative_md_block(source_ref, src_text, pages=pages)

`load_source_text` accepts PDF, HTML/SHTML, and plain text and returns
`(text, pages)` where `pages` is the 1-based list of PDF pages the text came
from (`None` for non-paginated sources).

Provenance note: this module is a reimplementation. The original lived in an
untracked `tools/` directory and was lost before the public release. The
markdown contract below (headings, trigger vocabularies, default label,
3000-char default budget) was recovered from the 1485 committed
`gt_evidence.md` files and is reproduced exactly; the PDF path was verified
byte-identical against `pypdf` page extraction. The whitespace produced by
HTML extraction and the exact truncation boundary of the original could not
be recovered, so regenerating a *pre-existing* period may show whitespace-level
diffs against the committed evidence. Output for new periods is correct and
self-consistent. See `evbench/maintainer/README.md`.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional, Sequence

__all__ = ["load_source_text", "build_narrative_md_block",
           "DRIVER_TRIGGERS", "RISK_TRIGGERS", "OUTLOOK_TRIGGERS"]

# --- the trigger vocabularies ----------------------------------------------
# These strings are printed verbatim into the section headings, so the order
# and spelling are part of the committed evidence format. Do not reorder.

DRIVER_TRIGGERS: tuple[str, ...] = (
    "due to", "driven by", "amid", "reflecting", "on the back of",
    "because of", "as a result of", "led by",
)
RISK_TRIGGERS: tuple[str, ...] = (
    "risk", "uncertainty", "concern", "headwind", "geopolitical",
    "caveats", "softening",
)
OUTLOOK_TRIGGERS: tuple[str, ...] = (
    "expected", "forecast", "project", "set to", "in the coming",
    "going forward", "likely to",
)

_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("driver", DRIVER_TRIGGERS),
    ("risk", RISK_TRIGGERS),
    ("outlook", OUTLOOK_TRIGGERS),
)

DEFAULT_VERBATIM_LABEL = "Verbatim bullets / executive summary"
DEFAULT_MAX_VERBATIM_CHARS = 3000

# Sentence splitter: break after . ! ? when followed by whitespace and a
# capital / digit / quote. Keeps "U.S." and "No. 3" intact well enough for
# trigger matching, which is substring-based anyway.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")

# Collapse the horizontal whitespace runs that PDF and HTML extraction leave
# behind, without touching line structure.
_TRAILING_WS = re.compile(r"[ \t]+(?=\n)")
_MANY_SPACES = re.compile(r"[ \t]{2,}")
_BLANK_RUN = re.compile(r"\n{3,}")


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Fold the Unicode spaces that PDF/HTML extractors emit into ASCII."""
    text = (text.replace("\xa0", " ")        # non-breaking space
                .replace(" ", " ")      # figure space
                .replace(" ", " ")      # narrow no-break space
                .replace("​", "")       # zero-width space
                .replace("\r\n", "\n")
                .replace("\r", "\n"))
    text = _MANY_SPACES.sub(" ", text)
    text = _TRAILING_WS.sub("", text)
    # Block-boundary insertion leaves long runs of empty lines; keep at most
    # one blank line so the verbatim budget is spent on prose, not whitespace.
    text = _BLANK_RUN.sub("\n\n", text)
    return text.strip("\n")


def _load_pdf(path: Path, max_pages: Optional[int]) -> tuple[str, list[int]]:
    """Extract text with pypdf, falling back to pdfplumber for scanned-ish
    files where pypdf returns nothing useful."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:                                # pragma: no cover
        raise ImportError(
            "reading PDF sources requires pypdf: pip install pypdf"
        ) from exc

    reader = PdfReader(str(path))
    limit = len(reader.pages) if max_pages is None else min(max_pages, len(reader.pages))
    chunks: list[str] = []
    pages: list[int] = []
    for i in range(limit):
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception:                                     # malformed page
            text = ""
        if text.strip():
            chunks.append(text)
            pages.append(i + 1)

    if not chunks:
        try:
            import pdfplumber
        except ImportError:
            return "", []
        with pdfplumber.open(str(path)) as doc:
            limit = len(doc.pages) if max_pages is None else min(max_pages, len(doc.pages))
            for i in range(limit):
                text = doc.pages[i].extract_text() or ""
                if text.strip():
                    chunks.append(text)
                    pages.append(i + 1)

    return "\n".join(chunks), pages


# Tags whose boundaries are meaningful paragraph breaks in the extracted text.
_BLOCK_TAGS = (
    "p", "div", "br", "li", "tr", "section", "article", "header", "footer",
    "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "dt", "dd",
)


def _main_content(soup):
    """Return the subtree most likely to hold the article body.

    Publisher landing pages carry far more navigation than prose, and a naive
    whole-page `get_text()` makes the verbatim excerpt a menu dump. Prefer the
    semantic containers; otherwise take the block with the most paragraph text.
    """
    for selector in ("main", "article", '[role="main"]',
                     ".field--body", ".entry-content", "#content", ".content"):
        node = soup.select_one(selector)
        if node and len(node.get_text(strip=True)) > 200:
            return node

    best, best_len = None, 0
    for node in soup.find_all(["div", "section"]):
        paras = node.find_all("p", recursive=False)
        length = sum(len(p.get_text(strip=True)) for p in paras)
        if length > best_len:
            best, best_len = node, length
    if best is not None and best_len > 200:
        return best
    return soup.body or soup


def _load_html(path: Path) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:                                # pragma: no cover
        raise ImportError(
            "reading HTML sources requires beautifulsoup4: pip install beautifulsoup4"
        ) from exc

    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        soup = BeautifulSoup(raw, "lxml")
    except Exception:
        soup = BeautifulSoup(raw, "html.parser")

    # NB: do not strip <form>. Classic ASP.NET WebForms pages (the U.S. Drought
    # Monitor archive, for one) wrap the entire body in a single server-side
    # form, so dropping it drops the whole document.
    for tag in soup(["script", "style", "noscript", "nav", "select"]):
        tag.decompose()

    root = _main_content(soup)
    # Make block boundaries survive get_text().
    for tag in root.find_all(_BLOCK_TAGS):
        tag.insert_after("\n")

    text = root.get_text(separator=" ")
    if len(text.strip()) < 200:
        # The container heuristic picked something near-empty — take the page.
        text = soup.get_text(separator=" ")
    return text


def load_source_text(path: Path | str,
                     max_pages: Optional[int] = None,
                     ) -> tuple[str, Optional[list[int]]]:
    """Return `(text, pages)` for a source report.

    `pages` is the 1-based list of PDF pages that contributed text, or `None`
    for HTML and plain-text sources. A missing or unreadable file yields
    `("", None)` so callers can skip the narrative block without branching on
    file existence — every call site guards with `if src_text:`.
    """
    path = Path(path)
    if not path.exists():
        return "", None

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text, pages = _load_pdf(path, max_pages)
        return _normalize(text), (pages or None)
    if suffix in (".html", ".htm", ".shtml", ".xhtml"):
        return _normalize(_load_html(path)), None
    try:
        return _normalize(path.read_text(encoding="utf-8", errors="replace")), None
    except OSError:
        return "", None


# ---------------------------------------------------------------------------
# Markdown block
# ---------------------------------------------------------------------------

def _truncate(text: str, budget: int) -> str:
    """Trim to at most `budget` characters, preferring a word boundary."""
    text = text.strip()
    if len(text) <= budget:
        return text
    window = text[:budget]
    cut = max(window.rfind(" "), window.rfind("\n"))
    if cut > budget * 0.6:                    # only if we keep most of the budget
        window = window[:cut]
    return window.rstrip()


def _sentences(text: str) -> list[str]:
    """Split into single-line sentences suitable for markdown bullets."""
    flat = " ".join(text.split())
    return [s.strip() for s in _SENTENCE_SPLIT.split(flat) if s.strip()]


def _matching(sentences: Iterable[str], triggers: Sequence[str]) -> list[str]:
    """Sentences containing any trigger, in document order, deduplicated."""
    out: list[str] = []
    seen: set[str] = set()
    for s in sentences:
        low = s.lower()
        if any(t in low for t in triggers) and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def build_narrative_md_block(source_ref: str,
                             source_text: str,
                             pages: Optional[Sequence[int]] = None,
                             verbatim_label: str = DEFAULT_VERBATIM_LABEL,
                             max_verbatim_chars: int = DEFAULT_MAX_VERBATIM_CHARS,
                             ) -> str:
    """Render the verbatim excerpt + trigger-sentence sections as markdown.

    `source_ref` (e.g. `"gt_source/2024-04.pdf"`) and `pages` are recorded as
    an HTML comment so the block stays traceable to its artifact without
    changing the rendered evidence that the judge reads.
    """
    excerpt = _truncate(source_text, max_verbatim_chars)
    sentences = _sentences(source_text)

    where = f"{source_ref}" + (f" pages={list(pages)}" if pages else "")
    parts = [
        f"<!-- narrative_extract: {where} -->",
        "",
        f"## {verbatim_label}",
        "",
        "```",
        excerpt,
        "```",
        "",
    ]

    for kind, triggers in _SECTIONS:
        parts.append(
            f"## {kind.capitalize()}-trigger sentences "
            f"(regex: {' / '.join(triggers)})"
        )
        parts.append("")
        hits = _matching(sentences, triggers)
        if hits:
            parts.extend(f"- {s}" for s in hits)
        else:
            parts.append(f"- (no {kind}-trigger sentences matched)")
        parts.append("")

    return "\n".join(parts)
