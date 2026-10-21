"""Parse an IRI ENSO QuickLook page into structured fields.

Page format (verified against March 2026 and current/April 2026):

  * "ENSO Update [<DD Month YYYY>]" header — issue date marker.
  * Synopsis paragraph at top: "<lead sentence describing current ENSO
    state and direction of transition>"
  * "The latest CCSR/IRI ENSO plume forecast favors <Phase> conditions
    at approximately NN% for <3-month season>" — probabilistic outlook.
  * IOD forecast paragraph: "The multi-model ensemble suggests ... IOD
    will remain <state> during ..."
  * Often compares to NOAA CPC forecast (Figure 1 vs Figure 3 language).
  * Discusses driver attribution (subsurface, SST, wind anomalies).
"""
from __future__ import annotations
import re
from pathlib import Path


# Anchors
ISSUE_DATE_RX = re.compile(
    r"ENSO Update \[(\w+\s+\d{1,2},?\s+20\d{2})\]", re.IGNORECASE
)
# Synopsis: first sentence containing 'equatorial Pacific' or 'ENSO-neutral'
SYNOPSIS_RX = re.compile(
    r"((?:As of [^.]{1,80}|The equatorial Pacific[^.]{1,100}|"
    r"At present[^.]{1,80}|Currently[^.]{1,80})\s*[^.]{0,200}\.)",
    re.IGNORECASE,
)
# Plume forecast probability: "favors <Phase> conditions at approximately NN%"
PLUME_RX = re.compile(
    r"CCSR/IRI ENSO plume forecast\s+(?:favors|gives|shows)\s+(?:a\s+)?"
    r"(?P<pct>\d{1,3})\s*%\s+chance\s+(?:of\s+)?(?P<phase>El Niño|La Niña|"
    r"ENSO[-\s]neutral)",
    re.IGNORECASE,
)
PLUME_FAVORS_RX = re.compile(
    r"plume\s+forecast\s+favors\s+(?P<phase>El Niño|La Niña|"
    r"ENSO[-\s]neutral)\s+conditions\s+at\s+approximately\s+(?P<pct>\d{1,3})\s*%",
    re.IGNORECASE,
)

# IOD forecast
IOD_RX = re.compile(
    r"((?:[A-Z][^.]{0,80}?)?\bIOD(?:\s+conditions?)?\s+"
    r"(?:will|is|remains?|exceed|stay|stays|continues?|tend(?:s|ed)|"
    r"oscillates?)\b[^.]{10,400}\.)",
    re.IGNORECASE,
)

# Driver sentences (IRI's vocabulary)
DRIVER_TRIGGERS = [
    r"subsurface (?:cooling|warming|temperatures?|anomal)",
    r"sea[\s-]surface temperature",
    r"\bSST anomal",
    r"thermocline",
    r"low[\s-]level wind anomal",
    r"trade winds?",
    r"easterly anomal",
    r"westerly anomal",
    r"warm pool",
    r"Walker circulation",
    r"\bMJO\b",
    r"plume forecast",
    r"\bIOD\b",
    r"multi-model ensemble",
    r"model (?:guidance|spread|agreement|consensus|bias)",
]
DRIVER_RX = re.compile(
    r"([A-Z][^.]*?(?:" + "|".join(DRIVER_TRIGGERS) + r")[^.]*?\.)",
    re.IGNORECASE,
)

# Comparison-to-CPC sentences (IRI often contrasts with official CPC)
CPC_COMPARE_RX = re.compile(
    r"((?:[A-Z][^.]*?)(?:CPC|official forecast|human forecasters?)"
    r"[^.]*?(?:differ|disagree|similar|consistent|aligned)[^.]*?\.)",
    re.IGNORECASE,
)

# Risk / uncertainty
RISK_TRIGGERS = [
    r"uncertaint", r"spread", r"disagree", r"low confidence",
    r"spring barrier", r"caveat", r"\bless likely\b", r"bias",
]
RISK_RX = re.compile(
    r"([A-Z][^.]*?(?:" + "|".join(RISK_TRIGGERS) + r")[^.]*?\.)",
    re.IGNORECASE,
)


def html_to_text(html: str) -> str:
    s = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    s = re.sub(r"<style[^>]*>.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    repl = {
        "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&#37;": "%", "&deg;": "°", "&ndash;": "–", "&mdash;": "—",
        "&quot;": '"', "&#39;": "'", "&apos;": "'",
        "&ntilde;": "ñ", "&Ntilde;": "Ñ",
    }
    for k, v in repl.items():
        s = s.replace(k, v)
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _normalize_phase(phase: str) -> str:
    p = re.sub(r"\s+", " ", phase).strip().lower()
    if "el niño" in p or "el nino" in p:
        return "El Niño"
    if "la niña" in p or "la nina" in p:
        return "La Niña"
    if "neutral" in p:
        return "ENSO-Neutral"
    return phase


_NAV_WORDS = ("Subscribe", "Menu", "About Us", "Maproom", "Mailing List",
              "Privacy Policy", "Contact Directory", "Fact Sheets",
              "Our Projects", "ENSO Resources", "Publications")

def _dedupe_keep_order(items):
    seen, out = set(), []
    for x in items:
        key = re.sub(r"\s+", " ", x).strip()
        # Skip navigation-chrome sentences (long + contains nav keywords)
        if len(key) > 600 and any(w in key for w in _NAV_WORDS):
            continue
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def parse_issue(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = html_to_text(raw)

    # Issue date
    issue_date = None
    m = ISSUE_DATE_RX.search(text)
    if m:
        issue_date = m.group(1)

    # Synopsis (lead sentence)
    synopsis = None
    sm = SYNOPSIS_RX.search(text)
    if sm:
        synopsis = re.sub(r"\s+", " ", sm.group(1)).strip()

    # Probabilistic outlook from plume forecast: flexible two-stage
    # extraction because IRI's phrasing varies issue-to-issue. Stage 1:
    # locate the first "plume forecast" or "plume forecasts" anchor;
    # Stage 2: within ~400 chars after the anchor, find the first phase
    # mention and (optionally) the first percentage.
    plume_phase = None
    plume_pct = None
    m = re.search(r"plume forecasts?\s+([^.]{1,500})", text, re.IGNORECASE)
    if m:
        ctx = m.group(1)
        # Try % first
        pm = re.search(r"\(?(\d{1,3})\s*%\)?", ctx)
        if pm:
            plume_pct = int(pm.group(1))
        # Find FIRST phase mention by position in the context (not by
        # arbitrary loop order — IRI often mentions both "ENSO-neutral"
        # and "El Niño" in the same sentence; the earliest mention is
        # the one tied to the main probability assertion).
        phase_positions = []
        for raw_phase in ("El Niño", "La Niña", "ENSO-neutral",
                          "ENSO neutral", "El Nino", "La Nina"):
            idx = ctx.lower().find(raw_phase.lower())
            if idx >= 0:
                phase_positions.append((idx, raw_phase))
        if phase_positions:
            phase_positions.sort()
            plume_phase = _normalize_phase(phase_positions[0][1])

    # IOD forecast
    iod_sentence = None
    m = IOD_RX.search(text)
    if m:
        iod_sentence = re.sub(r"\s+", " ", m.group(0)).strip()

    # Drivers (capped at 8)
    drivers = _dedupe_keep_order(
        [m.group(1).strip() for m in DRIVER_RX.finditer(text)]
    )[:8]

    # CPC-comparison sentence (often present, used to validate IRI vs CPC)
    cpc_compare = None
    m = CPC_COMPARE_RX.search(text)
    if m:
        cpc_compare = re.sub(r"\s+", " ", m.group(1)).strip()

    # Risks
    risks = _dedupe_keep_order(
        [m.group(1).strip() for m in RISK_RX.finditer(text)]
    )[:4]

    return {
        "issue_date": issue_date,
        "synopsis_summary": synopsis,
        "plume_outlook": {
            "phase": plume_phase,
            "probability_pct": plume_pct,
        },
        "iod_forecast": iod_sentence,
        "key_drivers": drivers,
        "cpc_iri_comparison": cpc_compare,
        "risks_uncertainties": " ".join(risks) if risks else None,
        "full_text": text[:8000],
    }
