"""Parse an NCEI monthly global-climate news article into structured fields.

NCEI publishes each monthly brief under `news/global-climate-<YYYYMM>` with a
stable narrative pattern:

  * Headline paragraph: "<Month YYYY> ranked as the Nth-warmest <Month> in
    the NN-year record, with a global temperature ... above the 20th-century
    average of ..."
  * Per-domain anomaly callouts (ocean, land, hemispheres, regions).
  * Sea ice section (Arctic + Antarctic monthly extent rank).
  * Optional: tropical-storm activity, snow cover, etc.

Numbers are presented in degrees Fahrenheit (°F) as headline; the
parenthetical metric (°C) is what NCEI considers the canonical value
(and is what Climate at a Glance returns). We pull the °C value
whenever present; if only °F is given we convert.

Best-effort. Fields that cannot be parsed reliably are left as None.
"""
from __future__ import annotations
import re
from pathlib import Path

from bs4 import BeautifulSoup


# --- core regex patterns ----------------------------------------------------

# Match a temperature like "+1.40°C" / "1.40°C" / "0.78 C" / "2.51 °F"
# Captures (sign, value, unit).
TEMP_RX = re.compile(
    r"([+\-]?)\s*([0-9]+(?:\.[0-9]+)?)\s*[°°]?\s*([CFcf])\b"
)

# Rank phrase: "ranked as the warmest" or "the third-warmest" or
# "9th-warmest" or "second warmest", etc.
ORDINAL_WORDS = {
    "warmest": 1,
    "second-warmest": 2, "second warmest": 2,
    "third-warmest": 3, "third warmest": 3,
    "fourth-warmest": 4, "fourth warmest": 4,
    "fifth-warmest": 5, "fifth warmest": 5,
    "sixth-warmest": 6, "sixth warmest": 6,
    "seventh-warmest": 7, "seventh warmest": 7,
    "eighth-warmest": 8, "eighth warmest": 8,
    "ninth-warmest": 9, "ninth warmest": 9,
    "tenth-warmest": 10, "tenth warmest": 10,
}

# Match "Nth-warmest" / "N-th warmest" / "Nth warmest" — N is an integer.
RANK_NUM_RX = re.compile(
    r"\b(\d{1,3})(?:st|nd|rd|th)[\-\s]*warmest\b", re.I,
)
# Match word ordinals (warmest/second-warmest/...)
RANK_WORD_RX = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in ORDINAL_WORDS.keys()) + r")\b",
    re.I,
)

# Match "in the <NNN>-year record" or "in the <NNN>-year (period of record|history)"
YEARS_RX = re.compile(
    r"in\s+the\s+(\d{2,4})[\-\s]*year\s+(?:record|period|history|climate\s+record)",
    re.I,
)

# Match common section / call-out headings.
ARCTIC_RX    = re.compile(r"Arctic[^.\n]{0,160}", re.I)
ANTARCTIC_RX = re.compile(r"Antarctic[^.\n]{0,160}", re.I)
SEA_ICE_RX   = re.compile(r"sea[\s\-]ice[^.\n]{0,200}", re.I)
OCEAN_RX     = re.compile(
    r"(?:global\s+)?ocean[^.\n]{0,200}(?:anomaly|temperature|warmest|record)",
    re.I,
)
LAND_RX      = re.compile(
    r"(?:global\s+)?land[^.\n]{0,200}(?:anomaly|temperature|warmest|record)",
    re.I,
)
NH_RX        = re.compile(
    r"Northern\s+Hemisphere[^.\n]{0,200}", re.I,
)
SH_RX        = re.compile(
    r"Southern\s+Hemisphere[^.\n]{0,200}", re.I,
)

# Regional callout headings. NCEI varies the section title; the body always
# starts with a regional name followed by anomaly / rank language.
REGION_NAMES = [
    "Africa", "Asia", "Europe", "North America", "South America",
    "Oceania", "Caribbean", "Hawaiian Region", "Hawaii",
    "Arctic", "Antarctic",
    "Atlantic Ocean", "Pacific Ocean", "Indian Ocean", "Southern Ocean",
    "Gulf of Mexico", "Mediterranean",
    "Contiguous U.S.", "Alaska",
]


# --- helpers ----------------------------------------------------------------

def f_to_c(value_f: float) -> float:
    """Convert a temperature anomaly from Fahrenheit to Celsius.

    For ANOMALIES (deltas) the conversion is value_c = value_f * 5/9, since
    the +32 offset cancels in a difference. The NCEI articles label °F
    headline anomalies; we apply the anomaly-conversion form here.
    """
    return value_f * 5.0 / 9.0


def first_temp_c(text: str) -> float | None:
    """Find the first temperature anomaly in `text`. Returns °C value (signed).

    Prefers a °C measurement if present in the same span; falls back to
    converting a °F number.
    """
    # Walk all matches in order; pick the first °C; if none, convert first °F.
    first_f: float | None = None
    for m in TEMP_RX.finditer(text):
        sign, val, unit = m.group(1), m.group(2), m.group(3)
        v = float(val) * (-1.0 if sign == "-" else 1.0)
        if unit in ("C", "c"):
            return round(v, 3)
        if first_f is None and unit in ("F", "f"):
            first_f = v
    if first_f is not None:
        return round(f_to_c(first_f), 3)
    return None


def extract_rank(text: str) -> int | None:
    """Find the global-rank for the headline 'Nth-warmest' phrase."""
    m = RANK_NUM_RX.search(text)
    if m:
        return int(m.group(1))
    m = RANK_WORD_RX.search(text)
    if m:
        return ORDINAL_WORDS[m.group(1).lower()]
    return None


def extract_total_years(text: str) -> int | None:
    """Find 'in the NNN-year record' style total-years phrase."""
    m = YEARS_RX.search(text)
    if m:
        return int(m.group(1))
    return None


def text_from_html(html: str) -> str:
    """Return paragraph-joined text from an NCEI news HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    # NCEI wraps the body content under <article> or <main>; fall back to
    # the whole document if neither is found.
    container = soup.find("article") or soup.find("main") or soup
    # Strip script/style.
    for s in container.find_all(["script", "style", "noscript"]):
        s.decompose()
    parts: list[str] = []
    for tag in container.find_all(["h1", "h2", "h3", "p", "li"]):
        t = tag.get_text(" ", strip=True)
        if t:
            parts.append(t)
    return "\n".join(parts)


def headline_paragraph(full_text: str) -> str:
    """Return the first paragraph that contains the rank phrase.

    Falls back to the first 2 paragraphs if no rank is found.
    """
    paras = [p.strip() for p in full_text.split("\n") if p.strip()]
    for p in paras:
        if RANK_NUM_RX.search(p) or RANK_WORD_RX.search(p):
            return p
    return "\n".join(paras[:2])


_SEA_ICE_WORD_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}


def extract_sea_ice_rank(text: str, hemisphere: str) -> int | None:
    """Best-effort: look for an 'Nth lowest/smallest/highest' near
    'Arctic' / 'Antarctic' sea-ice mentions.

    Try in order: numeric ordinal (Nth-lowest) → word ordinal
    (second-lowest) → bare "lowest/smallest" → None. The order matters:
    if the window contains "second-lowest", we want to return 2, not 1
    (the bare-"lowest" fallback would otherwise match a substring of
    "second-lowest").
    """
    rx = ARCTIC_RX if hemisphere == "arctic" else ANTARCTIC_RX
    for m in rx.finditer(text):
        window = text[m.start(): m.end() + 200]
        # 1) Nth-lowest / Nth-smallest
        nm = re.search(
            r"\b(\d{1,3})(?:st|nd|rd|th)[\-\s]+"
            r"(?:lowest|smallest|highest|largest|greatest)\b",
            window, re.IGNORECASE,
        )
        if nm:
            return int(nm.group(1))
        # 2) word-ordinal-lowest / smallest
        wm = re.search(
            r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)"
            r"[\-\s]+(?:lowest|smallest)\b",
            window, re.IGNORECASE,
        )
        if wm:
            return _SEA_ICE_WORD_ORDINALS[wm.group(1).lower()]
        # 3) bare "lowest"/"smallest" — only if it is not part of a
        #    larger ordinal expression already handled above.
        bm = re.search(
            r"(?<![\-\w])(lowest|smallest)\b", window, re.IGNORECASE,
        )
        if bm:
            return 1
    return None


def extract_regional_callouts(text: str) -> list[str]:
    """Return the list of region names that show up in callout-style spans.

    A region is "called out" when its name appears in a paragraph that ALSO
    contains a rank phrase or a temperature anomaly. De-duplicated, in
    first-mention order.
    """
    callouts: list[str] = []
    seen: set[str] = set()
    paras = text.split("\n")
    for p in paras:
        has_signal = bool(
            RANK_NUM_RX.search(p) or RANK_WORD_RX.search(p)
            or TEMP_RX.search(p)
            or re.search(r"\bwarmest\b|\bcoolest\b|\brecord\b", p, re.I)
        )
        if not has_signal:
            continue
        for name in REGION_NAMES:
            if name.lower() in p.lower() and name not in seen:
                callouts.append(name)
                seen.add(name)
    return callouts


def extract_sea_ice_status(text: str) -> str | None:
    """Pull the first sea-ice sentence (Arctic or Antarctic). Returns a
    cleaned single-line string for use in ground_truth.json.
    """
    # Prefer the first sentence containing 'sea ice'.
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if "sea ice" in sent.lower():
            return " ".join(sent.split())
    # Fall back: first Arctic or Antarctic sentence.
    for rx in (ARCTIC_RX, ANTARCTIC_RX):
        m = rx.search(text)
        if m:
            return " ".join(m.group(0).split())
    return None


def extract_ocean_anomaly_c(text: str) -> float | None:
    m = OCEAN_RX.search(text)
    return first_temp_c(m.group(0)) if m else None


def extract_land_anomaly_c(text: str) -> float | None:
    m = LAND_RX.search(text)
    return first_temp_c(m.group(0)) if m else None


def extract_nh_anomaly_c(text: str) -> float | None:
    m = NH_RX.search(text)
    return first_temp_c(m.group(0)) if m else None


def extract_sh_anomaly_c(text: str) -> float | None:
    m = SH_RX.search(text)
    return first_temp_c(m.group(0)) if m else None


# --- top-level entry point --------------------------------------------------

def parse_brief(path: Path) -> dict:
    """Parse an NCEI monthly brief HTML file into structured fields."""
    html = path.read_text(encoding="utf-8", errors="replace")
    text = text_from_html(html)
    head = headline_paragraph(text)

    global_anomaly_c = first_temp_c(head)
    if global_anomaly_c is None:
        # NCEI sometimes splits the rank phrase and the anomaly across
        # adjacent paragraphs. Fall back to scanning the full article.
        global_anomaly_c = first_temp_c(text)
    global_rank      = extract_rank(head)
    total_years      = extract_total_years(head)
    if total_years is None:
        # NCEI sometimes states the year count in the next paragraph.
        total_years = extract_total_years(text)

    arctic_rank    = extract_sea_ice_rank(text, "arctic")
    antarctic_rank = extract_sea_ice_rank(text, "antarctic")
    callouts       = extract_regional_callouts(text)
    sea_ice_status = extract_sea_ice_status(text)

    # The ocean / land / hemispheric anomaly_c fields are intentionally
    # omitted: NCEI no longer reports °C values for those breakdowns in
    # the modern brief format (they are described as ranks or relative
    # wording instead). See gt_evidence.md for the cross-checks against
    # the rank phrases that do appear.
    return {
        "global_anomaly_c":              global_anomaly_c,
        "global_rank_warmest":           global_rank,
        "total_years_compared":          total_years,
        "arctic_sea_ice_rank":           arctic_rank,
        "antarctic_sea_ice_rank":        antarctic_rank,
        "leading_regional_callouts":     callouts,
        "sea_ice_status":                sea_ice_status,
        "headline_paragraph":            head,
        "full_text":                     text,
    }
