"""Shared helpers for eurocontrol_monthly_network_ops_brief."""
from __future__ import annotations
import os
import datetime as dt
import re
import time
import urllib.request
from pathlib import Path

def _scenario_data_dir(script_file: str) -> Path:
    """Data directory for the scenario whose scripts/ contains `script_file`.

    Scripts live in evbench/maintainer/<tier>/<domain>/<id>/scripts/ while
    instances/ and source/ live under evbench/scenarios/.
    $TIMESAGE_DATA_ROOT overrides the data root.
    """
    spec = Path(script_file).resolve().parent.parent
    maintainer = spec.parents[2]
    rel = spec.relative_to(maintainer)
    return Path(os.environ.get("TIMESAGE_DATA_ROOT", maintainer.parent / "scenarios")) / rel



SCENARIO_ROOT = _scenario_data_dir(__file__)
TS_SOURCE = SCENARIO_ROOT / "timeseries_source"
GT_SOURCE = SCENARIO_ROOT / "gt_source"
INSTANCES = SCENARIO_ROOT / "instances"
ENV = SCENARIO_ROOT / "environment"

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

MONTH_NAMES = ["january", "february", "march", "april", "may", "june",
               "july", "august", "september", "october", "november", "december"]

# 24-month window: 2024-04 → 2026-03 (Eurocontrol publishes ~T+30 days; the
# 2026-04 NOR was not yet posted at scenario-build time).
REPORT_MONTHS = []
y, m = 2024, 4
for _ in range(24):
    REPORT_MONTHS.append((y, m))
    m += 1
    if m == 13:
        m = 1
        y += 1


def url_for(year: int, month: int) -> str:
    return (f"https://www.eurocontrol.int/publication/"
            f"network-operations-report-{MONTH_NAMES[month-1]}-{year}")


def ym_label(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def http_get(url: str, dest: Path, sleep_s: float = 1.5) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
    dest.write_bytes(body)
    time.sleep(sleep_s)


def parse_nor(html: str) -> dict:
    """Extract structured fields from a NOR HTML landing page."""
    clean = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    clean = re.sub(r"<style.*?</style>", "", clean, flags=re.S)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"&nbsp;", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    out: dict = {}

    # "Traffic in <Month> <Year> <N,NNN> average daily traffic"
    m = re.search(
        r"Traffic in (\w+)\s+(\d{4})\s+([\d,]+)\s+average daily traffic",
        clean, re.I)
    if m:
        out["data_month_name"] = m.group(1).title()
        out["data_year"] = int(m.group(2))
        out["avg_daily_traffic"] = int(m.group(3).replace(",", ""))

    # "+ X.X % compared to <Month> <Year>"
    m = re.search(
        r"([\+\-])\s*(\d+(?:\.\d+)?)\s*%?\s*%?\s*compared to\s+(\w+)\s+(\d{4})",
        clean, re.I)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        out["yoy_pct"] = sign * float(m.group(2))
        out["yoy_comparison_month"] = f"{m.group(3).title()} {m.group(4)}"

    # "<N,NNN> traffic on <DD> <Month> (peak day)"
    m = re.search(
        r"([\d,]+)\s+traffic on\s+(\d+)\s+(\w+)\s*\((?:peak[\s ]*day)?",
        clean, re.I)
    if m:
        out["peak_day_traffic"] = int(m.group(1).replace(",", ""))
        out["peak_day_date"] = f"{m.group(2)} {m.group(3).title()}"

    # ATFM delay — two formats:
    m = re.search(r"([\d,]+)\s+minutes of ATFM delay", clean, re.I)
    if m:
        out["atfm_delay_minutes"] = int(m.group(1).replace(",", ""))
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s+million minutes of ATFM delay",
                      clean, re.I)
        if m:
            out["atfm_delay_minutes"] = int(float(m.group(1)) * 1_000_000)

    # Extract a 2-3-sentence summary block — the paragraph that follows
    # the headline numbers and starts after "ATFM delay Support" or
    # similar. We'll capture the first 400 chars after the "Support" mark.
    idx = clean.find("ATFM delay")
    if idx >= 0:
        tail = clean[idx:idx + 1200]
        # Move past the immediate metric and grab the rest
        m = re.search(r"ATFM delay\s+([A-Z].{50,800})", tail)
        if m:
            out["raw_summary_block"] = m.group(1).strip()[:600]
    return out
