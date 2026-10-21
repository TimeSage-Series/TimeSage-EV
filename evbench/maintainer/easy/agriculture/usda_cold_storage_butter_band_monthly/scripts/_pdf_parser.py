"""Parser for the headline US butter stocks figure from a Cold Storage PDF.

Layout: page 3 (0-indexed) contains a single 3-row pdfplumber table.
Row index 2 carries the stacked column values. The table has 5 columns:
column 0 = year-ago stocks, column 1 = prior-month stocks, column 2 =
current-month stocks (the latest data month's value); columns 3 and 4
are percentage indices that we ignore.

Within each numeric column the rows of the dairy block are:
  index 0: '(1,000 pounds)' header line
  index 1: Pecans (shelled)
  index 2: Pecans (in-shell)
  index 3: Butter        <-- this is what we want
  index 4: American cheese
  index 5: Swiss cheese
  ...

Per pdfplumber's text-stacking convention each cell text is
'\n'-separated by row; row 3 of column 2 = butter stocks (current
data month) in 1,000 pounds.
"""
from __future__ import annotations
from pathlib import Path

import pdfplumber


def parse_butter_stocks(pdf_path: Path) -> int:
    """Return current-data-month US total butter stocks in 1,000 pounds.

    Raises ValueError if the PDF layout does not match expectations.
    """
    with pdfplumber.open(str(pdf_path)) as pdf:
        # Walk pages 2..6 looking for the dairy table.
        for i in range(2, min(8, len(pdf.pages))):
            page = pdf.pages[i]
            tables = page.extract_tables()
            for t in tables:
                if not t or len(t) < 3 or not t[0]:
                    continue
                header0 = " ".join((str(c) or "") for c in t[0])
                if "Stocks in all warehouses" not in header0:
                    continue
                # Found the dairy table on this page.
                val_row = t[2]
                if len(val_row) < 3:
                    continue
                current_col = val_row[2]    # column 2 = current data month
                if not current_col:
                    continue
                lines = [
                    ln.strip() for ln in current_col.split("\n")
                    if ln.strip()
                ]
                # First line is '(1,000 pounds)' header. After that, butter
                # is row index 3 of the table = 4th numeric line, so within
                # this stacked column it's lines[3] (header is lines[0],
                # pecans-shelled is lines[1], pecans-inshell is lines[2],
                # butter is lines[3]).
                if len(lines) < 4:
                    continue
                # Locate first numeric line (skip header text)
                numerics = [
                    ln for ln in lines
                    if any(ch.isdigit() for ch in ln)
                ]
                if len(numerics) < 4:
                    continue
                # numerics[0] = pecans shelled, [1] = pecans in-shell,
                # [2] = butter. Verified across cost0426 (288,834) and
                # cost0520 (368,666).
                butter_text = numerics[2]
                cleaned = butter_text.replace(",", "").strip()
                try:
                    return int(cleaned)
                except ValueError as e:
                    raise ValueError(
                        f"could not parse butter value {butter_text!r}: {e}"
                    )
    raise ValueError(f"butter table not found in {pdf_path.name}")
