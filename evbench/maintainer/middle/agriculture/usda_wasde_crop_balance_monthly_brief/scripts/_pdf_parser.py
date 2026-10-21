"""Parse a single WASDE PDF into the numeric fields both WASDE scenarios need.

Verified layout (Jan 2022 onward, WASDE issues #620..#670+):

  Page 11 — `U.S. Wheat Supply and Use 1/`
            Marketing-year columns: <MY-2>, <MY-1> Est., <MY> Proj. (prior month),
            <MY> Proj. (current month). The latest *current-month* projection is
            the rightmost number on each row. Key rows: `Ending Stocks`,
            `Yield per Harvested Acre`, `Exports`.

  Page 12 — `U.S. Feed Grain and Corn Supply and Use 1/`
            CORN section has the same 4-column structure as wheat.

  Page 15 — `U.S. Soybeans and Products Supply and Use (Domestic Measure) 1/`
            SOYBEANS section, same 4-column structure.

  Page 18 — `World Wheat Supply and Use 1/`
            World 3/ totals for each MY block; latest MY block is at the bottom
            and includes "(Proj.)" with prior/current revisions. We grab the
            ending-stocks value from the LAST "World" row's last numeric token.

  Page 22 — `World Corn Supply and Use 1/`
            Same layout as world wheat.

  Page 28 — `World Soybean Supply and Use 1/`
            Same layout.

US values are in million bushels (mbu); world values are in million metric
tons (mmt) per the WASDE convention.

The parser is intentionally tolerant: it locates each table by its page
header anchor (rather than by absolute page number) and skips pages that
don't match. Page numbers have been stable since at least Jan-2022.
"""
from __future__ import annotations
import re
from pathlib import Path

import pdfplumber


# --- helpers ------------------------------------------------------------- #

def _num(s: str) -> float | None:
    """Parse a WASDE number cell (handles commas)."""
    s = s.strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _last_row_value(text: str, row_prefix: str) -> float | None:
    """Return the LAST numeric token on a line that starts with `row_prefix`.

    The 4-column layout (`prior_MY`, `MY Est.`, `MY Proj Prev`, `MY Proj Cur`)
    means the rightmost token is the current month's value. Some rows have
    a trailing `Apr` or `Mar` label after "Ending Stocks, Total" — these are
    handled by the `Ending Stocks` row in the main table; the by-class rows
    are not used here.
    """
    # Tail may contain `NA` (no prior-month projection in first-projection
    # releases like 2024-05). Allow letters in the captured tail and rely on
    # the numeric tokenizer to pick out only the numeric cells. Use [ \t]
    # rather than \s so the tail can't span lines (\s would match \n and
    # cause cross-row contamination).
    pat = re.compile(
        rf"(?m)^[ \t]*{re.escape(row_prefix)}[ \t]+([\d,.\-\*A-Za-z/ \t]+)[ \t]*$"
    )
    m = pat.search(text)
    if not m:
        return None
    tail = m.group(1)
    toks = re.findall(r"-?\d[\d,]*\.?\d*", tail)
    if not toks:
        return None
    return _num(toks[-1])


def _last_world_value(text: str, anchor_prefix: str = "World 3/") -> float | None:
    """For the World <commodity> Supply and Use page, return the ending-stocks
    value (last numeric column) from the LATEST World row.

    The World tables are structured into blocks per marketing year. The last
    'World 3/' (or 'World 2/' for soybeans) row is the latest projection.
    """
    # Try both standard footnote variants.
    for prefix in (anchor_prefix, "World 2/", "World"):
        pat = re.compile(rf"(?m)^\s*{re.escape(prefix)}\s+([0-9].*)$")
        matches = list(pat.finditer(text))
        if matches:
            tail = matches[-1].group(1)
            toks = re.findall(r"-?\d[\d,]*\.?\d*", tail)
            if not toks:
                continue
            return _num(toks[-1])
    return None


def _marketing_year_from_text(text: str) -> str | None:
    """Pick the (latest) marketing-year label from a US table header line.

    The header looks like `2023/24 2024/25 Est. 2025/26 Proj. 2025/26 Proj.`
    The latest MY label is the rightmost YYYY/YY token.
    """
    yrs = re.findall(r"\b(20\d{2}/\d{2})\b", text)
    return yrs[-1] if yrs else None


# --- US tables ----------------------------------------------------------- #

def _find_page_by_anchor(pdf, anchor: str) -> str | None:
    for page in pdf.pages:
        t = page.extract_text() or ""
        if anchor in t:
            return t
    return None


def _find_pages_by_anchor(pdf, anchor: str) -> str:
    """Concatenate text of every page whose extract_text() contains the
    anchor — for world tables that span a main + (Cont'd.) page.
    """
    parts: list[str] = []
    for page in pdf.pages:
        t = page.extract_text() or ""
        if anchor in t:
            parts.append(t)
    return "\n".join(parts)


def _us_table(text: str) -> dict:
    """Extract ending_stocks_mbu, yield_bua, exports_mbu from a US US-* table."""
    out: dict[str, float | None] = {}
    # The main aggregate table sits at the top of the page. Find the
    # `Ending Stocks` line that appears BEFORE the by-class breakdown
    # (which starts at "U.S. Wheat by Class" / similar / or the SOYBEAN OIL block).
    # For wheat: stop at "U.S. Wheat by Class"; for corn: stop at "Avg. Farm Price";
    # for soybeans the main table also ends at "Avg. Farm Price".
    head = text
    # Cut off everything after a known by-class / sub-table heading so we
    # match the *first* (main-aggregate) Ending Stocks row.
    for cutoff in (
        "U.S. Wheat by Class",
        "SOYBEAN OIL",
        "SOYBEAN MEAL",
        "2/ For a breakout",
        "Note: Totals may not add",
    ):
        idx = head.find(cutoff)
        if idx > 0:
            head = head[:idx]
            break
    out["ending_stocks_mbu"] = _last_row_value(head, "Ending Stocks")
    out["yield_bua"] = _last_row_value(head, "Yield per Harvested Acre")
    out["exports_mbu"] = _last_row_value(head, "Exports")
    out["marketing_year"] = _marketing_year_from_text(head)
    return out


# --- World tables -------------------------------------------------------- #

_MONTH_ABBR = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
               7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}


def _world_table_value(text: str, release_month: int | None = None) -> float | None:
    """The world ending-stocks value (mmt) for the latest projection.

    Layout (continuation page, present for every month):
        World 3/ Mar <7 numbers>      <-- prior-month projection
        Apr      <7 numbers>          <-- CURRENT-month projection  ← we want this
        World Less China Mar ...
        Apr ...
        ...

    Strategy:
      1. Find the LAST `World 3/` (or `World 2/`) line in the text. That
         line *prefixes* the latest-projection block on the (Cont'd.) page.
      2. The very next non-empty line is the current-month projection (its
         first token is the current month abbreviation, e.g. "Apr").
      3. The last numeric token on that line is ending stocks.

    Falls back to:
      - if the next-line trick fails (older layouts where `Mar`/`Apr` aren't
        separated, or the current-month row is missing), use the LAST
        `World 3/` row's last numeric column.
      - filter to only `World 3/`/`World 2/` rows beginning with a numeric
        cell when no `(Cont'd.)` continuation exists.
    """
    lines = text.splitlines()
    # Find last World 3/ or World 2/ row index.
    world_idx = -1
    for i, ln in enumerate(lines):
        stripped = ln.lstrip()
        if stripped.startswith("World 3/") or stripped.startswith("World 2/"):
            world_idx = i
    if world_idx >= 0:
        cur_abbr = _MONTH_ABBR.get(release_month) if release_month else None
        # Walk forward up to 3 lines looking for the current-month continuation.
        for j in range(world_idx + 1, min(world_idx + 4, len(lines))):
            ln = lines[j].lstrip()
            # Skip blank/filler lines.
            if not ln:
                continue
            # Match a row that starts with a 3-letter month abbreviation.
            m = re.match(
                r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+([\d,.\-\s]+)$",
                ln,
            )
            if m:
                # If we know the release month, ensure it matches.
                if cur_abbr is None or m.group(1) == cur_abbr:
                    toks = re.findall(r"-?\d[\d,]*\.?\d*", m.group(2))
                    if toks:
                        return _num(toks[-1])
            # If a different "World" row appears, stop walking forward.
            if ln.startswith("World "):
                break
        # Fallback: use the World 3/ row itself (this row already shows the
        # current value on PDFs where there's no Mar/Apr split, e.g. older
        # 2022 issues with a different layout).
        world_line = lines[world_idx].lstrip()
        # If line begins with `World 3/ Mar` etc — we want the LAST numeric,
        # but that's the prior-month value. Only use it as a last resort.
        toks = re.findall(r"-?\d[\d,]*\.?\d*", world_line)
        if toks:
            return _num(toks[-1])
    return None


# --- public API ---------------------------------------------------------- #

def parse_wasde(pdf_path: Path, release_month: int | None = None) -> dict:
    """Parse one WASDE PDF and return all numeric fields needed by both
    WASDE scenarios.

    Returned keys (all floats unless noted):
      corn_us_ending_stocks_mbu
      corn_us_yield_bua
      corn_us_exports_mbu
      corn_marketing_year       (str)
      soybeans_us_ending_stocks_mbu
      soybeans_us_yield_bua
      soybeans_us_exports_mbu
      soybeans_marketing_year   (str)
      wheat_us_ending_stocks_mbu
      wheat_us_yield_bua
      wheat_us_exports_mbu
      wheat_marketing_year      (str)
      corn_world_ending_stocks_mmt
      soybeans_world_ending_stocks_mmt
      wheat_world_ending_stocks_mmt
      marketing_year            (str — the dominant US marketing year,
                                  defaults to corn's MY since corn is the
                                  largest US commodity by acreage)
    """
    with pdfplumber.open(str(pdf_path)) as pdf:
        wheat_us_text = _find_page_by_anchor(pdf, "U.S. Wheat Supply and Use")
        corn_us_text = _find_page_by_anchor(pdf, "U.S. Feed Grain and Corn Supply and Use")
        soy_us_text = _find_page_by_anchor(pdf, "U.S. Soybeans and Products Supply and Use")
        # World tables span main + (Cont'd.) pages — concatenate.
        wheat_world_text = _find_pages_by_anchor(pdf, "World Wheat Supply and Use")
        corn_world_text = _find_pages_by_anchor(pdf, "World Corn Supply and Use")
        soy_world_text = _find_pages_by_anchor(pdf, "World Soybean Supply and Use")

    out: dict = {}

    # --- US wheat ---
    if wheat_us_text:
        w = _us_table(wheat_us_text)
        out["wheat_us_ending_stocks_mbu"] = w.get("ending_stocks_mbu")
        out["wheat_us_yield_bua"] = w.get("yield_bua")
        out["wheat_us_exports_mbu"] = w.get("exports_mbu")
        out["wheat_marketing_year"] = w.get("marketing_year")

    # --- US corn (the CORN sub-block on the "Feed Grain and Corn" page) ---
    if corn_us_text:
        # Strip the FEED GRAINS block — only keep from "CORN" onward.
        idx = corn_us_text.find("CORN")
        corn_only = corn_us_text[idx:] if idx >= 0 else corn_us_text
        c = _us_table(corn_only)
        out["corn_us_ending_stocks_mbu"] = c.get("ending_stocks_mbu")
        out["corn_us_yield_bua"] = c.get("yield_bua")
        out["corn_us_exports_mbu"] = c.get("exports_mbu")
        # Marketing-year label sometimes lives in the page-header (above the
        # FEED GRAINS block) on newer (2026) issues; fall back to the full
        # page text for the MY label.
        out["corn_marketing_year"] = c.get("marketing_year") or _marketing_year_from_text(corn_us_text)

    # --- US soybeans (top block of the page) ---
    if soy_us_text:
        s = _us_table(soy_us_text)
        out["soybeans_us_ending_stocks_mbu"] = s.get("ending_stocks_mbu")
        out["soybeans_us_yield_bua"] = s.get("yield_bua")
        out["soybeans_us_exports_mbu"] = s.get("exports_mbu")
        out["soybeans_marketing_year"] = s.get("marketing_year")

    # --- World tables ---
    if wheat_world_text:
        out["wheat_world_ending_stocks_mmt"] = _world_table_value(wheat_world_text, release_month)
    if corn_world_text:
        out["corn_world_ending_stocks_mmt"] = _world_table_value(corn_world_text, release_month)
    if soy_world_text:
        out["soybeans_world_ending_stocks_mmt"] = _world_table_value(soy_world_text, release_month)

    out["marketing_year"] = out.get("corn_marketing_year") or out.get("soybeans_marketing_year") or out.get("wheat_marketing_year")
    return out
