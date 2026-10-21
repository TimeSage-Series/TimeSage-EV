"""Parse EIA Natural Gas Weekly Update HTML into Hard-tier fields.

NGW pages embed a 'Highlights' block followed by 5 standard sections:
    Prices  |  Supply & Demand  |  Liquefied Natural Gas  |  Storage  |
    Other Market Drivers / Rig Count

We capture:
  - henry_hub_spot_change_dollar (signed, USD/MMBtu, this week vs last)
  - henry_hub_spot_this_wed (USD/MMBtu)
  - direction (rising / falling / flat)
  - storage section verbatim
  - supply/demand section verbatim
  - LNG section verbatim
  - first 2500 chars of Highlights as conclusion_reference
  - driver / risk / outlook sentences (regex-anchored)
"""
from __future__ import annotations
import re
from pathlib import Path


def html_to_text(html: str) -> str:
    # Strip script/style blocks
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S|re.I)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.S|re.I)
    # HTML entities (basic)
    html = (html.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&#8217;", "'").replace("&#8211;", "-")
                .replace("&#176;", "deg").replace("&deg;", "deg")
                .replace("&#8230;", "...").replace("&rsquo;", "'")
                .replace("&ldquo;", '"').replace("&rdquo;", '"'))
    txt = re.sub(r"<[^>]+>", " ", html)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


# Format A (2026-01-22 era):
#   'rose $1.86 per million British thermal units (MMBtu) from $3.12/MMBtu last
#    Wednesday to $4.98/MMBtu yesterday'
# Format B (2025-07-24 era):
#   'fell 36 cents from $3.43 per million British thermal units (MMBtu) last
#    Wednesday to $3.07/MMBtu yesterday'
# Both flavours include "from $A ... to $B/MMBtu" — anchor on that and infer
# direction + magnitude from the prev->cur delta itself rather than the verb's
# numeric token.
# Variants observed across the 2025-07..2026-01 window:
#   'rose $1.86 per million British thermal units (MMBtu) from $3.12/MMBtu ... to $4.98/MMBtu'
#   'fell 36 cents from $3.43 per million British thermal units (MMBtu) ... to $3.07/MMBtu'
#   'fell about 20% during the past week, or down 94 cents from $4.61 ... to $3.67/MMBtu'
#   'rose 1 cent from $3.11 ... to $3.12/MMBtu'
#
# The 'verb + magnitude' phrasing varies wildly, but every issue contains
# 'from $A ... to $B/MMBtu'. Anchor on that and derive signed change from B-A.
_VERB_RX = re.compile(
    r"\b(rose|fell|increased|decreased|climbed|dropped|declined|gained|up|down)\b",
    re.I,
)
# NOTE: cannot use [^.] here because the dollar magnitudes ($1.86 etc.) contain
# decimal-point periods themselves and would short-circuit the match.
_FROM_TO_RX = re.compile(
    r"Henry\s+Hub\s+spot\s+price.{0,400}?"
    r"from\s+\$([\d.]+).{0,200}?to\s+\$([\d.]+)/MMBtu",
    re.I | re.S,
)


def extract_henry_hub(text: str) -> dict:
    m = _FROM_TO_RX.search(text)
    if not m:
        return {}
    prev = float(m.group(1))
    cur = float(m.group(2))
    signed = round(cur - prev, 4)
    # Recover the direction verb (first verb occurrence inside the match window).
    verb_m = _VERB_RX.search(text[max(0, m.start()):m.end()])
    verb = verb_m.group(1).lower() if verb_m else ("rose" if signed > 0 else
                                                    "fell" if signed < 0 else "unchanged")
    return {
        "henry_hub_change_dollar":  signed,
        "henry_hub_prev_wed":       prev,
        "henry_hub_this_wed":       cur,
        "verb":                     verb,
    }


def _slice_after(text: str, anchor_rx: re.Pattern, length: int) -> str:
    m = anchor_rx.search(text)
    return "" if not m else text[m.end():m.end() + length].strip()


def extract_highlights(text: str) -> str:
    m = re.search(r"Highlights:\s*\(For the week ending [^)]*\)", text, re.I)
    if not m:
        return ""
    return text[m.end():m.end() + 3500].strip()


def extract_supply_demand(text: str) -> str:
    return _slice_after(text, re.compile(r"Supply\s+and\s+Demand", re.I), 2500)


def extract_storage(text: str) -> str:
    return _slice_after(text, re.compile(r"\bStorage\b\s+Natural", re.I), 2500) \
        or _slice_after(text, re.compile(r"\bStorage\b", re.I), 2500)


def extract_lng(text: str) -> str:
    return _slice_after(text, re.compile(r"Liquefied\s+Natural\s+Gas", re.I), 2200)


_DRIVER_TRIG = re.compile(
    r"\b(temperatures?|heating\s+degree\s+days?|HDD|cooling|weather|cold\s+front|"
    r"production|consumption\s+rose|consumption\s+fell|"
    r"LNG\s+(exports|cargoes|deliveries)|storage\s+(withdrawal|injection)|"
    r"pipeline\s+(maintenance|outage|disruption)|"
    r"rig\s+count|hurricane|tropical\s+storm)\b", re.I)
_RISK_TRIG = re.compile(
    r"\b(below\s+the\s+five-year\s+average|above\s+the\s+five-year\s+average|"
    r"tight\s+(supply|inventory)|low\s+storage|"
    r"forecast.{0,40}(cold|warm|heat|cool|surge|spike)|"
    r"price\s+volatility|risk\s+of|likelihood\s+of)\b", re.I)
_OUTLOOK_TRIG = re.compile(
    r"\b(forecast|expected|projected|next\s+week|coming\s+(week|month)|"
    r"NOAA\s+forecast|expecting|anticipat|outlook)\b", re.I)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text)
    return [p.strip() for p in parts if 40 < len(p.strip()) < 600]


def _match(text: str, trig: re.Pattern, limit: int) -> list[str]:
    out = []; seen = set()
    for s in _sentences(text):
        if trig.search(s):
            sig = s[:80]
            if sig in seen:
                continue
            seen.add(sig)
            out.append(s)
        if len(out) >= limit:
            break
    return out


def parse_ngw(html_path: Path) -> dict:
    text = html_to_text(html_path.read_text(encoding="utf-8", errors="replace"))
    hh = extract_henry_hub(text)
    highlights = extract_highlights(text)
    return {
        **hh,
        "highlights_verbatim":  highlights,
        "supply_demand_text":   extract_supply_demand(text),
        "storage_text":         extract_storage(text),
        "lng_text":             extract_lng(text),
        "driver_sentences":     _match(text, _DRIVER_TRIG, 10),
        "risk_sentences":       _match(text, _RISK_TRIG, 6),
        "outlook_sentences":    _match(text, _OUTLOOK_TRIG, 6),
    }
