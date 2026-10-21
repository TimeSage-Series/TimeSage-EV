"""Parse a CPC ENSO Diagnostic Discussion shtml file into structured fields.

The CPC ENSO DD is a tightly-formatted document with a stable shape:

    ENSO Alert System Status: <Status>

    Synopsis: <1-2 sentence headline>

    <Body paragraphs: drivers (SST anomalies, subsurface, low-level winds,
     convection, trade winds, Walker circulation, model spread); outlook
     ("favored ... <Phase> through <season>"); probabilistic guidance
     ("NN% chance of <Phase> during <season>"); risks / uncertainties.>

This parser extracts:
  - alert_status            : str (one of ALERT_STATUS_OPTIONS, normalized
                                   to Unicode form)
  - synopsis_summary        : str (verbatim, 1-2 sentences after "Synopsis:")
  - key_drivers             : list[str] (verbatim sentences matching driver
                                         anchors)
  - outlook_3mo             : { phase: str, probability_pct: int|None,
                                target_season: str|None }
  - risks_uncertainties     : str (verbatim sentences matching risk/
                                   uncertainty anchors)
  - full_text               : str (the cleaned full body, for the LLM judge
                                   to reference verbatim)
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    html_to_text, ALERT_STATUS_NORMALIZE, ALERT_STATUS_OPTIONS,
)


# Anchor: "ENSO Alert System Status: <value>"
ALERT_RX = re.compile(
    r"ENSO\s+Alert\s+System\s+Status:\s*([^\n]+?)(?:\s{2,}|\s+Synopsis|\s+&nbsp|$)",
    re.IGNORECASE,
)
SYNOPSIS_RX = re.compile(
    r"Synopsis:\s*([A-Z][^.]+?\.(?:\s+[A-Z][^.]+?\.){0,3})",
    re.S,
)

# Driver-sentence triggers — the analytical vocabulary CPC uses to describe
# oceanic + atmospheric drivers. Each match contributes a verbatim
# sentence to key_drivers.
DRIVER_TRIGGERS = [
    r"sea[\s-]surface temperature",
    r"\bSST anomal",
    r"subsurface (?:cooling|warming|temperatures?)",
    r"thermocline",
    r"low[\s-]level wind anomal",
    r"trade winds?",
    r"easterly anomal",
    r"westerly anomal",
    r"\bconvection",
    r"Walker circulation",
    r"warm pool",
    r"upwelling",
    r"\bMJO\b",
    r"forecast (?:team|guidance)",
    r"NMME",
    r"model (?:guidance|spread|agreement|consensus)",
]
DRIVER_RX = re.compile(
    r"([A-Z][^.]*?(?:" + "|".join(DRIVER_TRIGGERS) + r")[^.]*?\.)",
    re.IGNORECASE,
)

# Risk / uncertainty triggers
RISK_TRIGGERS = [
    r"uncertaint",
    r"spread among",
    r"disagree",
    r"low confidence",
    r"spring barrier",
    r"caveat",
    r"\bless likely\b",
    r"\brisk\b",
    r"\bunusual\b",
]
RISK_RX = re.compile(
    r"([A-Z][^.]*?(?:" + "|".join(RISK_TRIGGERS) + r")[^.]*?\.)",
    re.IGNORECASE,
)

# Probabilistic outlook: "NN% chance of <Phase>"
PROB_RX = re.compile(
    r"(\d{1,3})\s*%\s*chance\s*(?:of\s*)?(El Niño|La Niña|ENSO[\s-]neutral)",
    re.IGNORECASE,
)
# Forecast team "favors" phrase — backup phase detector
FAVORS_RX = re.compile(
    r"(?:favors?|favored to|expected to (?:emerge|persist|continue|develop)|"
    r"likely to (?:emerge|persist|continue|develop|transition))\s+"
    r"(?:[a-zA-Z- ]{0,40}\s+)?(El Niño|La Niña|ENSO[\s-]neutral|"
    r"ENSO[\s-]Neutral)",
    re.IGNORECASE,
)


def _normalize_alert(raw: str) -> str:
    s = re.sub(r"\s+", " ", raw).strip().strip("&; ,.")
    # CPC issues a compound status during transition months (e.g.
    # 'El Niño Advisory / La Niña Watch' — El Niño is ending, La Niña
    # is being watched). The FIRST clause is the current/active status.
    if "/" in s:
        s = s.split("/")[0].strip()
    # Try canonical Unicode form first
    for opt in ALERT_STATUS_OPTIONS:
        if s.lower() == opt.lower():
            return opt
    # Try ASCII-Unicode normalization
    if s in ALERT_STATUS_NORMALIZE:
        return ALERT_STATUS_NORMALIZE[s]
    for ascii_form, canon in ALERT_STATUS_NORMALIZE.items():
        if s.lower() == ascii_form.lower():
            return canon
    # If the status contains a known phase substring, classify best-effort
    s_low = s.lower()
    if "not active" in s_low:
        return "Not Active"
    return s   # fall through — record raw


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen, out = set(), []
    for x in items:
        key = re.sub(r"\s+", " ", x).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def parse_issue(path: Path) -> dict:
    raw_html = path.read_text(encoding="utf-8", errors="replace")
    text = html_to_text(raw_html)

    # Alert status
    alert: str | None = None
    m = ALERT_RX.search(text)
    if m:
        alert = _normalize_alert(m.group(1))

    # Synopsis
    synopsis: str | None = None
    sm = SYNOPSIS_RX.search(text)
    if sm:
        synopsis = re.sub(r"\s+", " ", sm.group(1)).strip()

    # Key drivers
    drivers = _dedupe_keep_order(
        [m.group(1).strip() for m in DRIVER_RX.finditer(text)]
    )[:8]   # cap at 8

    # Risks / uncertainties
    risks = _dedupe_keep_order(
        [m.group(1).strip() for m in RISK_RX.finditer(text)]
    )[:4]
    risks_text = " ".join(risks) if risks else None

    # Probabilistic outlook — pick the FIRST explicit (chance, phase) pair
    outlook_phase: str | None = None
    outlook_pct: int | None = None
    pm = PROB_RX.search(text)
    if pm:
        outlook_pct = int(pm.group(1))
        phase = pm.group(2)
        outlook_phase = re.sub(r"[\s-]+", "-", phase).replace("ENSO-neutral",
                                                              "ENSO-Neutral")
        if outlook_phase.lower() in ("el-niño", "el niño"):
            outlook_phase = "El Niño"
        elif outlook_phase.lower() in ("la-niña", "la niña"):
            outlook_phase = "La Niña"
        elif outlook_phase.lower() in ("enso-neutral",):
            outlook_phase = "ENSO-Neutral"
    if outlook_phase is None:
        fm = FAVORS_RX.search(text)
        if fm:
            phase = fm.group(1)
            outlook_phase = (
                "El Niño" if "ni" in phase.lower() and "el" in phase.lower()
                else "La Niña" if "ni" in phase.lower() and "la" in phase.lower()
                else "ENSO-Neutral"
            )

    return {
        "alert_status": alert,
        "synopsis_summary": synopsis,
        "key_drivers": drivers,
        "outlook_3mo": {
            "phase": outlook_phase,
            "probability_pct": outlook_pct,
        },
        "risks_uncertainties": risks_text,
        "full_text": text,
    }
