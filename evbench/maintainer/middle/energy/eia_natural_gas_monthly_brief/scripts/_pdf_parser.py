"""Parse EIA Natural Gas Monthly PDF using pdfplumber.

NGM is dominated by structured tables. The Highlights page is metadata, not
data — the numeric series we need live in Tables 1 (supply & disposition),
2 (consumption by sector), 3 (national average prices), and 8 (underground
storage). The earlier prose-based extractor returned null on every issue
because no sentence-form numbers exist in this report.

For each issue, we extract the LATEST month of data reported (typically
issue_month minus 2 — e.g. the April 2026 issue contains data through
February 2026). The (data_year, data_month) pair is taken from Table 1's
last monthly row and is the cross-table anchor; every other table is read
at its own last-monthly-row position, which should match.
"""
from __future__ import annotations
import calendar
import datetime as dt
import re
from pathlib import Path

from pypdf import PdfReader

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_RX = re.compile(r"^\s*(" + "|".join(MONTHS) + r")\s+(.+)$")
# Table 3 in pypdf output spaces the year as '2 0 2 4'; Tables 1/2/8 use
# the plain '2024' form. Accept either by collapsing whitespace first.
YEAR_RX = re.compile(r"^\s*(2\s*0\s*\d\s*\d)\s*$")


def _read_text(path: Path, max_pages: int = 40) -> str:
    """Extract text from the first `max_pages` pages of the NGM PDF.

    Tables 1, 2, 3 live on pages ~7-12 and Table 8 lives on page ~32 in
    the current NGM layout, so 40 pages is plenty of margin. Reading the
    full ~130-page report makes parsing 5-10x slower for no extra signal.

    2024-vintage NGM PDFs use non-breaking spaces (\\xa0) inside titles and
    table cells. Normalize to regular ASCII whitespace so the section /
    monthly-row regexes work uniformly across the corpus.
    """
    r = PdfReader(str(path))
    parts: list[str] = []
    for p in r.pages[:max_pages]:
        try:
            parts.append(p.extract_text() or "")
        except Exception:
            parts.append("")
    raw = "\n".join(parts)
    return raw.replace("\xa0", " ").replace("‐", "-").replace("‑", "-")


def _section(text: str, table_num: int) -> str:
    """Return text between 'Table N.' header (start of line) and the next
    'Table M.' header. Anchoring to start-of-line avoids matching prose
    references like 'as shown in Table 2.' that appear in footnotes."""
    rx = re.compile(rf"^\s*Table\s+{table_num}\.\s+[A-Z]", re.M)
    m = rx.search(text)
    if not m:
        return ""
    rest = text[m.end():]
    m2 = re.search(r"^\s*Table\s+\d+\.\s+[A-Z]", rest, re.M)
    return rest[:m2.start()] if m2 else rest


def _parse_num(tok: str) -> float | None:
    if not tok or tok in ("*", "--"):
        return None
    t = tok
    while t and t[0] in "EeRr*":
        t = t[1:]
    t = t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _monthly_rows(section: str) -> list[tuple[int, str, list[float | None]]]:
    """Walk a table section, returning (year, month_name, parsed_values).
    Year is tracked from the most recent stand-alone year-header line."""
    rows: list[tuple[int, str, list[float | None]]] = []
    current_year: int | None = None
    for line in section.splitlines():
        ym = YEAR_RX.match(line)
        if ym:
            current_year = int(re.sub(r"\s+", "", ym.group(1)))
            continue
        mm = MONTH_RX.match(line)
        if not mm or current_year is None:
            continue
        toks = mm.group(2).split()
        # Skip page-header lines like 'April 2026' (single token = year).
        if len(toks) < 5:
            continue
        rows.append((current_year, mm.group(1), [_parse_num(t) for t in toks]))
    return rows


def _last_monthly(section: str):
    rows = _monthly_rows(section)
    return rows[-1] if rows else None


def _month_to_num(name: str) -> int:
    return MONTHS.index(name) + 1


def _days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def parse(path: Path) -> dict:
    text = _read_text(path)
    out: dict = {
        "total_consumption_bcfd": None,
        "dry_gas_production_bcfd": None,
        "henry_hub_spot_price_usd_mmbtu": None,
        "working_storage_total_bcf": None,
        "leading_consumption_sector": None,
        "_sector_breakdown_bcf": None,
        "data_year": None,
        "data_month": None,
        "data_period_end": None,
        "report_reference": "",
    }

    # Table 1 — Supply & Disposition. Columns (after month token):
    # [0] gross_withdrawals  [1] marketed  [2] ngpl  [3] dry_gas
    # [4] supplemental       [5] net_exports  [6] net_storage_withdrawal
    # [7] balancing_item     [8] consumption
    t1 = _last_monthly(_section(text, 1))
    data_year = data_month = None
    if t1 and len(t1[2]) >= 9:
        yr, mo, vals = t1
        data_year, data_month = yr, _month_to_num(mo)
        days = _days_in_month(yr, data_month)
        if vals[8] is not None:
            out["total_consumption_bcfd"] = round(vals[8] / days, 2)
        if vals[3] is not None:
            out["dry_gas_production_bcfd"] = round(vals[3] / days, 2)

    # Table 2 — Consumption by sector. Columns:
    # [0] lease  [1] pipeline  [2] residential  [3] commercial
    # [4] industrial  [5] electric_power  [6] vehicle  [7] total_delivered
    # [8] total_consumption  [9] heating_value
    t2 = _last_monthly(_section(text, 2))
    if t2 and len(t2[2]) >= 10:
        vals = t2[2]
        sectors = {
            "residential":    vals[2],
            "commercial":     vals[3],
            "industrial":     vals[4],
            "electric_power": vals[5],
        }
        valid = {k: v for k, v in sectors.items() if v is not None}
        out["_sector_breakdown_bcf"] = sectors
        if valid:
            out["leading_consumption_sector"] = max(valid, key=valid.get)

    # Table 3 — National average prices. Columns:
    # [0] ngpl_composite  [1] natural_gas_spot (Henry Hub, $/MMBtu per fn b)
    # [2] citygate  [3] residential_price  [4] res_% ... etc
    t3 = _last_monthly(_section(text, 3))
    if t3 and len(t3[2]) >= 2 and t3[2][1] is not None:
        out["henry_hub_spot_price_usd_mmbtu"] = round(t3[2][1], 3)

    # Table 8 — Underground storage. Columns:
    # [0] base_gas  [1] working_gas  [2] total  [3] yoy_volume  [4] yoy_pct
    # [5] injections  [6] withdrawals  [7] net_withdrawals
    t8 = _last_monthly(_section(text, 8))
    if t8 and len(t8[2]) >= 2 and t8[2][1] is not None:
        out["working_storage_total_bcf"] = t8[2][1]

    if data_year is not None and data_month is not None:
        out["data_year"] = data_year
        out["data_month"] = data_month
        out["data_period_end"] = dt.date(
            data_year, data_month, _days_in_month(data_year, data_month)
        ).isoformat()

    # Verbatim Highlights body (NGM page ~5 begins with "Highlights\nThis
    # issue of the Natural Gas Monthly..."). Skip the TOC entry that just
    # has "Highlights ............... 1".
    m = re.search(r"Highlights\s*\n\s*This issue of the Natural Gas Monthly",
                  text)
    if m:
        head = text[m.start():m.start() + 2500]
    else:
        m = re.search(r"\bHighlights\b\s*\n\s*[A-Z]", text)
        head = text[m.start():m.start() + 2500] if m else text[:2500]
    out["report_reference"] = head.strip()

    return out


if __name__ == "__main__":
    import json, sys
    print(json.dumps(parse(Path(sys.argv[1])), indent=2, default=str))
