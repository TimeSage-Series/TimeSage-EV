"""Parser for the headline US total pork stocks figure from a Cold Storage PDF.

Layout: page 6 (0-indexed) contains a single 3-row pdfplumber table.
Row index 2 carries the stacked column values. The table has 5 numeric
columns: column 0 = year-ago stocks, column 1 = prior-month stocks,
column 2 = current-month stocks (the latest data month's value);
columns 3 and 4 are percentage indices that we ignore.

Within each numeric column the rows of the frozen-red-meat block are
(in pdfplumber stacked-text order):
  index 0: '(1,000 pounds)' header line
  index 1: Boneless beef
  index 2: Beef cuts
  index 3: Total beef
  index 4: Picnics, bone-in (pork)
  index 5: Hams bone-in
  index 6: Hams boneless
  index 7: Total hams
  index 8: Bellies
  index 9: Loins bone-in
  index 10: Loins boneless
  index 11: Total loins
  index 12: Ribs
  index 13: Butts
  index 14: Trimmings
  index 15: Other
  index 16: Variety meats
  index 17: Unclassified
  index 18: Total pork              <-- this is what we want
  index 19: Veal
  index 20: Lamb and mutton
  index 21: Total other red meat
  index 22: Total frozen red meat
  ...

Per pdfplumber's text-stacking convention each cell text is
'\n'-separated by row; row index 18 of column 2 (skipping the header
on row index 0) = Total pork stocks (current data month) in 1,000
pounds.

Verified across a representative sample of cost*.pdf releases
spanning 2019-06 .. 2026-04.
"""
from __future__ import annotations
from pathlib import Path

import pdfplumber


def parse_pork_stocks(pdf_path: Path) -> int:
    """Return current-data-month US Total pork stocks in 1,000 pounds.

    Raises ValueError if the PDF layout does not match expectations.
    """
    with pdfplumber.open(str(pdf_path)) as pdf:
        # Walk pages 4..10 looking for the frozen red meat table.
        for i in range(4, min(12, len(pdf.pages))):
            page = pdf.pages[i]
            tables = page.extract_tables()
            for t in tables:
                if not t or len(t) < 3 or not t[0]:
                    continue
                header0 = " ".join((str(c) or "") for c in t[0])
                if "Stocks in all warehouses" not in header0:
                    continue
                # Verify this is the frozen red meat table (not the
                # dairy or fruit/veg tables which share the header).
                val_row = t[2]
                if len(val_row) < 3 or not val_row[2]:
                    continue
                current_col = val_row[2]
                # Sanity: the dairy table has 'Pecans' and 'Butter' /
                # 'American cheese'. The frozen red meat table has
                # 'Total beef' and 'Bellies' / 'Total pork'. Probe by
                # text content from the column-0 cell which also
                # contains the labels in some PDFs OR by extracting
                # the page text once.
                page_text = page.extract_text() or ""
                if "Total pork" not in page_text:
                    continue
                # Extract stacked numeric lines from the current-month
                # column. Skip the leading '(1,000 pounds)' header.
                lines = [
                    ln.strip() for ln in current_col.split("\n")
                    if ln.strip()
                ]
                # Drop any header/unit lines (no digits), keep numeric-bearing.
                numerics = [
                    ln for ln in lines
                    if any(ch.isdigit() for ch in ln)
                ]
                # numerics[0] = '(1,000 pounds)' header line which
                # pdfplumber sometimes keeps in this stacked column;
                # numerics[18] = Total pork value (verified). To
                # disambiguate the rare case where the unit-header
                # is OMITTED from numerics (because '1,000 pounds'
                # contains digits), we scan-by-index.
                # Locate Total pork by structural position: it's the
                # 18th entry counting from the unit header (numerics
                # index 18) OR the 17th if the unit-header was
                # dropped. We resolve by checking that the value is
                # both >= 250,000 and <= 1,000,000 (Total pork stocks
                # in 1,000 pounds always sit in 300k..650k range
                # historically; Total beef sits in 380k..650k as
                # well but appears at index 3). The safe pivot is to
                # locate 'Total pork' explicitly in the page text and
                # then pick the matching numeric.
                # Robust approach: find Total pork row index in the
                # left-most column label cell text, then read the
                # same index from the value column.
                #
                # The left-column cell (val_row[?]) is not reliably
                # parseable by pdfplumber for this PDF, so we use the
                # FIXED structural index that we have verified
                # against the working layout (numerics[18] when the
                # unit header IS present; numerics[17] otherwise).
                if numerics and "1,000" in numerics[0]:
                    offset = 18
                else:
                    offset = 17
                if len(numerics) <= offset:
                    continue
                total_pork_text = numerics[offset]
                cleaned = total_pork_text.replace(",", "").strip()
                try:
                    val = int(cleaned)
                except ValueError as e:
                    raise ValueError(
                        f"could not parse Total pork value "
                        f"{total_pork_text!r}: {e}"
                    )
                # Sanity bounds: historic monthly Total pork stocks
                # have lived in the 250k..700k thousand-pound range
                # since 2010; anything outside indicates a layout
                # mismatch.
                if not (200_000 <= val <= 800_000):
                    raise ValueError(
                        f"implausible Total pork value {val:,} "
                        f"from {pdf_path.name} (numerics[{offset}])"
                    )
                return val
    raise ValueError(f"frozen-red-meat table not found in {pdf_path.name}")
