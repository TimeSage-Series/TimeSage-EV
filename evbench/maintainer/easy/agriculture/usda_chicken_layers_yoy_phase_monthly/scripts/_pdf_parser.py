"""Parser for the 'Layers during <data-month>' figures from a Chickens
and Eggs PDF.

Layout: the PDF has multiple 'Layers on Hand and Eggs Produced by Type
and Molt -- United States: <month1>-<month2> <year1> and <year2>'
sections. We want the LATER (data-month) section. Each section starts
with 'Layers during <data-month>' and the first sub-row is
'Total layers ... 1,000 <prior_year_count> <current_year_count> <pct>'.

Both per-year figures are precise to 1,000 head.
"""
from __future__ import annotations
import re
from pathlib import Path

import pdfplumber

# Capture: "Layers during March" then later "Total layers ... 1,000 360,746 377,386 105"
# Some monthly releases use "All layers" instead of "Total layers" (notably
# the December/January release uses "All layers" on the December page).
PAT = re.compile(
    r"Layers during\s+(?P<month>\w+)\s+.*?"
    r"(?:Total layers|All layers)\s*[\.\s]+\s*1,000\s+"
    r"(?P<prior>[\d,]+)\s+(?P<current>[\d,]+)\s+(?P<pct>\d+)",
    re.DOTALL,
)

# Capture the page heading. Two known formats:
#   "United States: February-March 2025 and 2026"
#   "United States: December-January 2022-2024"   (December page uses span)
HEADER_PAT_AND = re.compile(
    r"Layers on Hand and Eggs Produced by Type and Molt"
    r"\s*[–—\-]+\s*United States:\s*"
    r"(\w+)-(\w+)\s+(\d{4})\s+and\s+(\d{4})",
    re.DOTALL,
)
HEADER_PAT_SPAN = re.compile(
    r"Layers on Hand and Eggs Produced by Type and Molt"
    r"\s*[–—\-]+\s*United States:\s*"
    r"(\w+)-(\w+)\s+(\d{4})-(\d{4})",
    re.DOTALL,
)

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
MONTH_NUM = {name: i + 1 for i, name in enumerate(MONTH_NAMES)}


def parse_layers(pdf_path: Path, target_data_year: int, target_data_month: int):
    """Return (layers_prior_year_klb, layers_current_klb) for the target
    data month, in 1,000-head units (raw NASS precision).

    Searches each page for a 'Layers on Hand and Eggs Produced by Type
    and Molt' header that spans TWO consecutive months over TWO
    consecutive years, then matches the 'Layers during <data-month>'
    sub-section.
    """
    with pdfplumber.open(str(pdf_path)) as pdf:
        target_name = MONTH_NAMES[target_data_month - 1]
        for i in range(0, len(pdf.pages)):
            page = pdf.pages[i]
            text = page.extract_text() or ""
            hdr = HEADER_PAT_AND.search(text)
            data_year_for_page = None
            if hdr:
                m1_name, m2_name, y1, y2 = hdr.groups()
                # "<m1>-<m2> <y1> and <y2>": m1 is in y1, m2 is in y2;
                # current-year columns are y2. Data year = y2.
                data_year_for_page = int(y2)
            else:
                hdr = HEADER_PAT_SPAN.search(text)
                if hdr:
                    m1_name, m2_name, y1, y2 = hdr.groups()
                    # "<m1>-<m2> <y1>-<y2>": Dec-Jan format. The page
                    # covers TWO Dec-Jan pairs across a 3-year span, but
                    # the table tabulates only the LATEST pair --
                    # columns labelled (y2-1, y2). The data month is
                    # December of the data year, which is y2-1.
                    # Verified on ckeg0124 (span 2022-2024 -> data year
                    # 2023) and ckeg0125 (span 2023-2025 -> data year
                    # 2024).
                    data_year_for_page = int(y2) - 1
                else:
                    continue
            if data_year_for_page != target_data_year:
                continue
            if m1_name != target_name and m2_name != target_name:
                continue
            for match in PAT.finditer(text):
                if match.group("month") == target_name:
                    prior = int(match.group("prior").replace(",", ""))
                    current = int(match.group("current").replace(",", ""))
                    return prior, current
    raise ValueError(
        f"could not locate Layers during {MONTH_NAMES[target_data_month-1]} "
        f"{target_data_year} in {pdf_path.name}"
    )
