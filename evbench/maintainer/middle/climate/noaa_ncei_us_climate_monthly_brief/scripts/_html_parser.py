"""Parse an NCEI monthly U.S. (national) climate news article.

Headline patterns we extract for the contiguous-U.S. (CONUS) scope:
  * Temperature:  "average temperature for the contiguous U.S. (CONUS) in
                   <Month> was X.X°F, Y.Y°F (above|below) the [...]
                   average, ranking ..."
  * Precipitation: "average precipitation for the contiguous U.S. in
                    <Month> was X.XX inches, Y.YY inch (above|below)
                    average, [placing|ranking] ..."

The extractors are CONUS-scoped: we walk the parsed paragraphs in order
and pick the FIRST paragraph that mentions "CONUS" or "contiguous U.S."
This avoids accidentally picking up Alaska / Hawai'i headline numbers
(NCEI publishes a CONUS paragraph followed by separate Alaska / Hawai'i
paragraphs in the same brief).
"""
from __future__ import annotations
import re
from pathlib import Path

from bs4 import BeautifulSoup


# --- generic sub-patterns ---------------------------------------------------

# A degree-F temperature like "73.4°F" / "73.4 °F".
_FLOAT = r"\d+(?:\.\d+)?"

# CONUS-scope detector. NCEI uses both "contiguous U.S." and the
# parenthetical "(CONUS)" abbreviation.
_CONUS_RX = re.compile(
    r"contiguous\s+U\.S\.|CONUS\b", re.IGNORECASE,
)

# Headline-temperature line. The anomaly clause can follow with a comma,
# an "and", or a "which is" connector. The "average" reference can be
# modified by any short qualifier ("20th-century", "long-term",
# "1991-2020") or be bare.
TEMP_F_RX = re.compile(
    rf"(?P<value>{_FLOAT})\s*°?F"
    rf"[\s,;]+(?:which\s+is\s+|and\s+)?"
    rf"(?P<anom>{_FLOAT})\s*°?F\s+"
    rf"(?P<dir>above|below)\s+(?:the\s+)?"
    rf"(?:[A-Za-z0-9][\w\-]*\s+)?"     # optional modifier
    rf"average",
    re.IGNORECASE,
)

# Precipitation pattern is structurally similar but with "inches"/"inch".
# NCEI sometimes inserts "in <Month>," or "which is" between value and
# anomaly. Note: write `inch(?:es)?` (not `inches?`); the `?` after `s`
# would otherwise apply only to the single 's' and require a literal `inche`.
PRECIP_INCHES_RX = re.compile(
    rf"(?P<value>{_FLOAT})\s+inch(?:es)?"
    rf"(?:\s+in\s+\w+)?"               # optional "in October" etc.
    rf"[\s,;]+(?:which\s+is\s+|and\s+)?"
    rf"(?P<anom>{_FLOAT})\s+inch(?:es)?\s+"
    rf"(?P<dir>above|below)\s+(?:the\s+)?"
    rf"(?:[A-Za-z0-9][\w\-]*\s+)?"
    rf"average",
    re.IGNORECASE,
)

# Tier-style rank: "ranking in the warmest third of the 131-year record".
# Also accepts "middle third" → midpoint of total years.
TEMP_RANK_TIER_RX = re.compile(
    r"rank(?:ing|ed|s)?\s+in\s+the\s+"
    r"(?P<dir>warmest|coolest|hottest|coldest|middle)\s+"
    r"(?P<tier>third|half|quarter|fifth|tenth|twentieth)\s+of\s+the\s+"
    r"(?P<years>\d+)[\s-]year\s+(?:period\s+of\s+)?record",
    re.IGNORECASE,
)

# Numeric ordinal: "Nth-warmest" with optional "rank/ranked/ranking" prefix.
# Examples:
#   "ranking 18th warmest in the 130-year record"
#   "ranking as the 18th-warmest February in the 132-year record"
#   "experienced the eighth-warmest October in the 131-year record"
TEMP_RANK_NUM_RX = re.compile(
    r"(?:rank(?:ing|ed|s)?\s+(?:as\s+the\s+)?|the\s+)"
    r"(?P<n>\d+)(?:st|nd|rd|th)[\s-]?"
    r"(?P<dir>warmest|coolest|hottest|coldest)"
    r"(?:[^.\n]*?in\s+the\s+(?P<years>\d+)[\s-]year\s+(?:period\s+of\s+)?record)?",
    re.IGNORECASE,
)

# Word ordinal: "ranking second warmest" / "the eighth-warmest October ...".
WORD_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
TEMP_RANK_WORD_RX = re.compile(
    r"(?:rank(?:ing|ed|s)?\s+(?:as\s+the\s+)?|\bthe\s+)"
    r"(?P<word>first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)"
    r"[\s-]"
    r"(?P<dir>warmest|coolest|hottest|coldest)"
    r"(?:[^.\n]*?in\s+the\s+(?P<years>\d+)[\s-]year\s+(?:period\s+of\s+)?record)?",
    re.IGNORECASE,
)

# Bare "ranked warmest"/"ranking as the warmest" (no ordinal prefix → 1).
TEMP_RANK_BARE_RX = re.compile(
    r"rank(?:ing|ed|s)?\s+(?:as\s+)?(?:the\s+)?"
    r"(?P<dir>warmest|coolest|hottest|coldest)"
    r"(?:[^.\n]*?in\s+the\s+(?P<years>\d+)[\s-]year\s+(?:period\s+of\s+)?record)?",
    re.IGNORECASE,
)

# Tier-style precipitation rank: "placing the month in the driest third
# of the 131-year record".
PRECIP_RANK_TIER_RX = re.compile(
    r"(?:rank(?:ing|ed|s)?|plac(?:ing|ed)|put(?:ting)?)\s+"
    r"(?:[^.\n]*?in\s+the\s+|the\s+(?:month|year)\s+in\s+the\s+)"
    r"(?P<dir>upper|lower|driest|wettest)\s+"
    r"(?P<tier>third|half|quarter|fifth|tenth|twentieth)\s+of\s+the\s+"
    r"(?:historical\s+|\d+[\s-]year\s+)?record",
    re.IGNORECASE,
)

TIER_DIR_TO_KEY = {
    "warmest": "upper", "hottest": "upper", "driest": "lower",
    "coolest": "lower", "coldest": "lower", "wettest": "upper",
    "upper": "upper", "lower": "lower",
}
TIER_TO_FRACTION = {
    "third": 1/3, "half": 1/2, "quarter": 1/4,
    "fifth": 1/5, "tenth": 1/10, "twentieth": 1/20,
}


# --- callout sub-patterns ---------------------------------------------------

STATE_NAMES = [
    "Alabama","Alaska","Arizona","Arkansas","California","Colorado",
    "Connecticut","Delaware","Florida","Georgia","Hawaii","Idaho",
    "Illinois","Indiana","Iowa","Kansas","Kentucky","Louisiana","Maine",
    "Maryland","Massachusetts","Michigan","Minnesota","Mississippi",
    "Missouri","Montana","Nebraska","Nevada","New Hampshire","New Jersey",
    "New Mexico","New York","North Carolina","North Dakota","Ohio",
    "Oklahoma","Oregon","Pennsylvania","Rhode Island","South Carolina",
    "South Dakota","Tennessee","Texas","Utah","Vermont","Virginia",
    "Washington","West Virginia","Wisconsin","Wyoming",
    "District of Columbia","Puerto Rico","Guam","U.S. Virgin Islands",
]
EXTREME_TRIGGERS = [
    r"tornadoes?", r"flooding|floods?", r"hurricanes?|tropical storms?",
    r"wildfires?", r"drought", r"heat\s*wave", r"cold\s*wave|polar vortex",
    r"snowstorms?|blizzards?", r"derechos?", r"hailstorms?",
    r"landslides?", r"ice\s*storms?", r"dust\s*storms?",
]
EXTREME_RX = re.compile(
    r"\b(" + "|".join(EXTREME_TRIGGERS) + r")\b", re.IGNORECASE
)


# --- helpers ----------------------------------------------------------------

def text_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("article") or soup.find("main") or soup
    for s in container.find_all(["script", "style", "noscript"]):
        s.decompose()
    parts = []
    for tag in container.find_all(["h1", "h2", "h3", "p", "li"]):
        t = tag.get_text(" ", strip=True)
        if t:
            parts.append(t)
    return "\n".join(parts)


_SEASONAL_SKIP_RX = re.compile(
    r"meteorological\s+(?:summer|fall|autumn|winter|spring)"
    r"|year[\s-]to[\s-]date"
    r"|January[\-–—]"                   # year-to-date: "January–<Month>"
    r"|January\s+through\s+"
    # Seasonal headline summary sentences ("warmest winter on record",
    # "the sixth-warmest spring on record", etc.). Plain month-name-only
    # references ("February was the fourth warmest") are kept.
    r"|\b(?:winter|spring|summer|fall|autumn)\s+(?:on\s+record|season|for\s+)"
    r"|\b(?:warmest|coolest|hottest|coldest|driest|wettest)\s+"
    r"(?:winter|spring|summer|fall|autumn)\b",
    re.IGNORECASE,
)


def _is_seasonal(para: str) -> bool:
    return bool(_SEASONAL_SKIP_RX.search(para))


def _first_sentence(para: str) -> str:
    """Return the first sentence of a paragraph.

    NCEI weaves the monthly headline together with a subsequent
    year-to-date sentence inside the same paragraph (e.g. the April 2025
    CONUS-temperature paragraph). Restricting parsing to the first
    sentence ensures we extract monthly numbers, not YTD numbers.
    """
    m = re.search(r"\.\s+(?=[A-Z\"“])", para)
    return para[:m.end()].strip() if m else para.strip()


def _conus_paragraphs(text: str) -> list[str]:
    """Return the paragraphs that mention CONUS / contiguous U.S., in order.

    NCEI lays out the brief as:
        Headline / Temperature header
        Para 1: CONUS temperature (headline numbers)        <- we want this
        Para 2: CONUS year-to-date / season temperature
        Para 3: Alaska temperature
        Para 4: Hawai'i temperature
        Precipitation header
        Para 5: CONUS precipitation                          <- we want this
        Para 6: CONUS season precipitation
        ...

    We keep all CONUS paragraphs; downstream extractors take the first
    one that yields a value.
    """
    return [p for p in text.split("\n") if p.strip() and _CONUS_RX.search(p)]


def _temp(text: str) -> tuple[float | None, float | None]:
    """Headline CONUS monthly temperature + anomaly (°F).

    We take the FIRST CONUS paragraph that contains a "X.X°F, Y.Y°F
    (above|below) ... average" pattern. Year-to-date / seasonal
    paragraphs come later in the brief and are skipped because we want
    the monthly headline.
    """
    for para in _conus_paragraphs(text):
        # Restrict parsing to the first sentence of each CONUS paragraph.
        # NCEI sometimes packs a monthly-headline sentence and a year-to-date
        # sentence into the same paragraph; the first sentence is always the
        # monthly headline.
        sent = _first_sentence(para)
        if _is_seasonal(sent):
            continue
        m = TEMP_F_RX.search(sent)
        if m:
            v = float(m.group("value"))
            anom = float(m.group("anom"))
            if m.group("dir").lower() == "below":
                anom = -anom
            return v, anom
    return None, None


def _precip(text: str) -> tuple[float | None, float | None]:
    """Headline CONUS monthly precipitation + anomaly (inches)."""
    for para in _conus_paragraphs(text):
        sent = _first_sentence(para)
        if _is_seasonal(sent):
            continue
        if "precipitation" not in sent.lower() and "rainfall" not in sent.lower():
            continue
        m = PRECIP_INCHES_RX.search(sent)
        if m:
            v = float(m.group("value"))
            anom = float(m.group("anom"))
            if m.group("dir").lower() == "below":
                anom = -anom
            return v, anom
    return None, None


def _temp_rank(text: str) -> tuple[int | None, int | None]:
    """Headline CONUS temperature rank + total years."""
    for para in _conus_paragraphs(text):
        sent = _first_sentence(para)
        if _is_seasonal(sent):
            continue
        # Anchor to the temperature paragraph: must contain °F or be a
        # standalone "experienced the Nth-warmest <month>" sentence.
        is_temp_para = ("°F" in sent or "°f" in sent.lower()
                        or re.search(r"warmest|coolest|hottest|coldest",
                                     sent, re.IGNORECASE))
        if not is_temp_para:
            continue
        # Try numeric → word → tier → bare in that order.
        m = TEMP_RANK_NUM_RX.search(sent)
        if m:
            years = int(m.group("years")) if m.group("years") else None
            return int(m.group("n")), years
        m = TEMP_RANK_WORD_RX.search(sent)
        if m:
            years = int(m.group("years")) if m.group("years") else None
            return WORD_ORDINALS[m.group("word").lower()], years
        m = TEMP_RANK_TIER_RX.search(sent)
        if m:
            total = int(m.group("years"))
            tier = m.group("tier").lower()
            frac = TIER_TO_FRACTION.get(tier, 0.5)
            direction = m.group("dir").lower()
            if direction in ("warmest", "hottest"):
                rank = max(1, round(total * frac))
            elif direction == "middle":
                rank = max(1, round(total * 0.5))
            else:
                rank = total - max(1, round(total * frac)) + 1
            return rank, total
        m = TEMP_RANK_BARE_RX.search(sent)
        if m:
            years = int(m.group("years")) if m.group("years") else None
            return 1, years
    return None, None


def _precip_rank_tier(text: str) -> str | None:
    """CONUS precipitation rank tier (e.g. 'upper-third', 'lower-third')."""
    for para in _conus_paragraphs(text):
        sent = _first_sentence(para)
        if _is_seasonal(sent):
            continue
        if "precipitation" not in sent.lower() and "rainfall" not in sent.lower():
            continue
        m = PRECIP_RANK_TIER_RX.search(sent)
        if m:
            direction = m.group("dir").lower()
            tier = m.group("tier").lower()
            key = TIER_DIR_TO_KEY.get(direction, direction)
            if key not in ("upper", "lower"):
                # NCEI sometimes uses "middle third" etc.; the answer
                # schema only accepts upper/lower so we leave it unset.
                return None
            return f"{key}-{tier}"
    return None


def _state_callouts(text):
    out, seen = [], set()
    for sent in re.split(r"(?<=[.!?])\s+", text):
        cue = (re.search(r"\b(?:warmest|coolest|driest|wettest|record|"
                         r"above[\s-]average|below[\s-]average)\b",
                         sent, re.IGNORECASE)
               or re.search(r"\d+\.\d+\s*°?F", sent))
        if not cue:
            continue
        for s in STATE_NAMES:
            if re.search(rf"\b{re.escape(s)}\b", sent) and s not in seen:
                out.append(s); seen.add(s)
    return out


def _extreme_callouts(text):
    # Canonical labels MUST match answer_schema.json's enum exactly.
    # Map matched surface text to its canonical schema enum value.
    out, seen = [], set()
    for m in EXTREME_RX.finditer(text):
        surface = m.group(1).lower()
        canonical = _ext_canon(surface)
        if canonical and canonical not in seen:
            out.append(canonical); seen.add(canonical)
    return out[:8]


def _ext_canon(surface: str) -> str:
    s = surface.strip().lower()
    if s in ("tornado", "tornadoes"):    return "tornadoes"
    if s in ("flood", "floods", "flooding"): return "flooding"
    if s in ("hurricane", "hurricanes"): return "hurricane"
    if "tropical storm" in s:            return "tropical storm"
    if s in ("wildfire", "wildfires"):   return "wildfires"
    if s == "drought":                   return "drought"
    if "heat" in s and "wave" in s:      return "heatwave"
    if "cold" in s and "wave" in s:      return "cold snap"
    if "polar vortex" in s:              return "cold snap"
    if s in ("blizzard", "blizzards"):   return "blizzard"
    if "snowstorm" in s:                 return "winter storm"
    if "ice" in s and "storm" in s:      return "winter storm"
    if "derecho" in s:                   return "severe storms"
    if "hailstorm" in s or s == "hail":  return "hail"
    if "landslide" in s:                 return "landslides"
    if "dust storm" in s:                return "severe storms"
    return ""


def headline_paragraph(text: str) -> str:
    """Return the first CONUS paragraph containing a temperature reading."""
    for p in _conus_paragraphs(text):
        if TEMP_F_RX.search(p):
            return p
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    return paras[0] if paras else ""


def parse_brief(path: Path) -> dict:
    html = path.read_text(encoding="utf-8", errors="replace")
    text = text_from_html(html)
    head = headline_paragraph(text)

    us_t, us_t_anom = _temp(text)
    rank, total = _temp_rank(text)
    us_p, us_p_anom = _precip(text)
    p_tier = _precip_rank_tier(text)
    states = _state_callouts(text)
    extremes = _extreme_callouts(text)

    return {
        "us_temp_f": us_t,
        "us_temp_anomaly_f": us_t_anom,
        "us_temp_rank_warmest": rank,
        "total_years_compared": total,
        "us_precip_inches": us_p,
        "us_precip_anomaly_inches": us_p_anom,
        "us_precip_rank_tier": p_tier,
        "leading_state_callouts": states,
        "extreme_weather_callouts": extremes,
        "headline_paragraph": head,
        "full_text": text,
    }
