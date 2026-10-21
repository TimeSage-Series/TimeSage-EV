"""Parse a Copernicus C3S monthly Surface Air Temperature page.

Page format (verified against April 2025):
  * "<Month YYYY> was the [Nth-]warmest <Month> globally, with an average
    ERA5 surface air temperature of X.XX°C, Y.YY°C above the 1991-2020
    average for <Month>."
  * Optional comparison line: "<Month YYYY> was Z.ZZ°C cooler than the
    record <Month> of <PREV_YYYY>."
  * Optional 12-month-running average context.
  * Optional Europe / regional callouts within the body.
"""
from __future__ import annotations
import re
from pathlib import Path

from bs4 import BeautifulSoup


# Headline: "April 2025 was the second-warmest April globally, with an
# average ERA5 surface air temperature of 14.96°C, 0.60°C above the
# 1991-2020 average for April."
HEADLINE_RX = re.compile(
    r"(?P<month>\w+)\s+(?P<year>\d{4})\s+was\s+the\s+"
    r"(?P<rank_word>warmest|second[-\s]warmest|third[-\s]warmest|"
    r"fourth[-\s]warmest|fifth[-\s]warmest|sixth[-\s]warmest|"
    r"seventh[-\s]warmest|joint[-\s]\w+[-\s]warmest)\s+"
    r"\w+\s+(?:on\s+record\s+)?globally,?\s+with\s+an\s+average\s+(?:ERA5\s+)?surface\s+air\s+temperature\s+of\s+(?P<sat>\d+\.\d+)\s*°?C,\s*"
    r"(?P<anom>\d+\.\d+)\s*°?C\s+above\s+the\s+1991[\s-]2020\s+average",
    re.IGNORECASE,
)


# Variant 2: "<Month> YYYY was the second-warmest <Month> globally, after
# <Month> 2023, with an average ERA5 surface air temperature of X.XX°C,
# Y.YY°C above the 1991-2020 average for <Month>." (e.g. Sep 2024)
HEADLINE_AFTER_RX = re.compile(
    r"(?P<month>\w+)\s+(?P<year>\d{4})\s+was\s+the\s+"
    r"(?P<rank_word>warmest|second[-\s]warmest|third[-\s]warmest|"
    r"fourth[-\s]warmest|fifth[-\s]warmest|sixth[-\s]warmest|"
    r"seventh[-\s]warmest)\s+\w+\s+globally,?\s+after\s+\w+\s+\d{4},?\s+"
    r"with\s+an\s+average\s+(?:ERA5\s+)?surface\s+air\s+temperature\s+of\s+"
    r"(?P<sat>\d+\.\d+)\s*°?C,\s*(?P<anom>\d+\.\d+)\s*°?C\s+above\s+the\s+"
    r"1991[\s-]2020\s+average",
    re.IGNORECASE,
)

# Variant 3: "<Month> YYYY was N.NN°C warmer than the 1991-2020 average
# for <Month>, with an absolute surface air temperature of X.XX°C."
# (Newer 2025-26 phrasing where rank is not given in the headline.)
HEADLINE_ABS_RX = re.compile(
    r"(?P<month>\w+)\s+(?P<year>\d{4})\s+was\s+(?P<anom>\d+\.\d+)\s*°?C\s+"
    r"warmer\s+than\s+the\s+1991[\s-]2020\s+average\s+for\s+\w+,?\s+"
    r"with\s+an\s+absolute\s+surface\s+air\s+temperature\s+of\s+"
    r"(?P<sat>\d+\.\d+)\s*°?C",
    re.IGNORECASE,
)

# Comparison: "April 2025 was 0.07°C cooler than the record April of 2024"
COMPARE_RX = re.compile(
    r"(?P<month>\w+)\s+(?P<year>\d{4})\s+was\s+(?P<delta>\d+\.\d+)\s*°?C\s+"
    r"(?P<dir>cooler|warmer|colder|hotter)\s+than\s+the\s+record",
    re.IGNORECASE,
)

# Europe callout: "Europe ... was ... above/below the 1991-2020 average"
EUROPE_RX = re.compile(
    r"(?:European\s+land\s+temperature|temperature\s+over\s+Europe|"
    r"Europe\s+as\s+a\s+whole)[^.]*?(\d+\.\d+)\s*°?C[^.]*?"
    r"(?:above|below)\s+(?:the\s+)?1991[\s-]2020\s+average",
    re.IGNORECASE,
)

WORD_RANK = {
    "warmest": 1,
    "second-warmest": 2, "second warmest": 2,
    "third-warmest": 3, "third warmest": 3,
    "fourth-warmest": 4, "fourth warmest": 4,
    "fifth-warmest": 5, "fifth warmest": 5,
    "sixth-warmest": 6, "sixth warmest": 6,
    "seventh-warmest": 7, "seventh warmest": 7,
}


def text_from_html(html: str) -> str:
    """Naive HTML→text: drop script/style + tags, decode entities, collapse whitespace.

    BeautifulSoup container-based extraction was dropping the headline
    paragraph for Copernicus because the bulletin uses bespoke <div>
    markup instead of <article>/<main>. The naive regex pass preserves
    inline text reliably.
    """
    s = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    repl = {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&#176;": "°", "&deg;": "°", "&ndash;": "–", "&mdash;": "—",
        "&quot;": '"', "&#39;": "'", "&apos;": "'",
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _rank_from_word(word: str) -> int | None:
    w = re.sub(r"\s+", " ", word.lower())
    # Handle "joint-Nth-warmest" by stripping "joint-"
    w = re.sub(r"^joint[-\s]", "", w)
    for k, v in WORD_RANK.items():
        if w == k:
            return v
    return None


def headline_paragraph(text: str) -> str:
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    for p in paras:
        if HEADLINE_RX.search(p):
            return p
    return paras[0] if paras else ""


def parse_brief(path: Path) -> dict:
    html = path.read_text(encoding="utf-8", errors="replace")
    text = text_from_html(html)
    head = headline_paragraph(text)

    global_anomaly_c = None
    global_sat_c = None
    global_rank = None
    for rx in (HEADLINE_RX, HEADLINE_AFTER_RX):
        m = rx.search(text)
        if m:
            global_sat_c = float(m.group("sat"))
            global_anomaly_c = float(m.group("anom"))
            global_rank = _rank_from_word(m.group("rank_word"))
            break
    if global_anomaly_c is None:
        m = HEADLINE_ABS_RX.search(text)
        if m:
            global_sat_c = float(m.group("sat"))
            global_anomaly_c = float(m.group("anom"))
            # Rank not directly given by HEADLINE_ABS_RX; try to find it
            # in a nearby sentence ("Nth-warmest" / "warmest on record")
            rm = re.search(r"(warmest|second[-\s]warmest|third[-\s]warmest|fourth[-\s]warmest|fifth[-\s]warmest)\s+\w+\s+(?:on\s+record\s+)?(?:globally|in\s+the\s+ERA5)", text, re.IGNORECASE)
            if rm:
                global_rank = _rank_from_word(rm.group(1))

    cm = COMPARE_RX.search(text)
    delta_to_record_c = None
    record_year = None
    if cm:
        delta = float(cm.group("delta"))
        if cm.group("dir").lower() in ("cooler", "colder"):
            delta = -delta
        delta_to_record_c = delta
        # Try to grab the "of YYYY" reference year
        rm = re.search(r"record\s+\w+\s+of\s+(\d{4})", text, re.IGNORECASE)
        if rm:
            record_year = int(rm.group(1))

    europe_anomaly_c = None
    em = EUROPE_RX.search(text)
    if em:
        europe_anomaly_c = float(em.group(1))

    return {
        "global_anomaly_c": global_anomaly_c,
        "global_sat_c": global_sat_c,
        "global_rank_warmest": global_rank,
        "delta_to_record_c": delta_to_record_c,
        "record_year": record_year,
        "europe_anomaly_c": europe_anomaly_c,
        "headline_paragraph": head,
        "full_text": text,
    }
