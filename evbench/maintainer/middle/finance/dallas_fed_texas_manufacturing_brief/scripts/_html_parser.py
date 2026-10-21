"""Parse Dallas Fed TMOS monthly HTML page for diffusion indexes + narrative.

The report body uses phrasings like:
  'production index ... jumped 12 points to 19.0, a reading suggestive of ...'
  'general business activity index fell two points to -2.3'
  'company outlook index rebounded into positive territory, rising seven points to 3.0'
  'outlook uncertainty index fell eight points to 17.9'
  'employment index was unchanged at 5.7'
  'new orders ... increased four points to 9.9'
  'shipments index rose 13 points to 15.0'

Numeric values are sometimes given as numerals (12) and sometimes as words
(twelve). We anchor on the 'to <number>' tail which is always numeric.
"""
from __future__ import annotations
import re
from pathlib import Path


def _html_to_text(html: str) -> str:
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S|re.I)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.S|re.I)
    html = (html.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&#8217;", "'").replace("&#8211;", "-")
                .replace("&rsquo;", "'").replace("&ldquo;", '"').replace("&rdquo;", '"'))
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Generic 'X index ... to <number>' or '... at <number>' pattern.
def _index_extractor(name_rx: str):
    return re.compile(
        rf"\b{name_rx}\s+index[^.]*?(?:\bto\b|\bat\b)\s+(-?[\d]+(?:\.\d+)?)",
        re.I | re.S,
    )


_INDEX_RX = {
    "production":           _index_extractor(r"production"),
    "general_activity":     _index_extractor(r"general\s+business\s+activity"),
    "company_outlook":      _index_extractor(r"company\s+outlook"),
    "outlook_uncertainty":  _index_extractor(r"outlook\s+uncertainty"),
    "new_orders":           _index_extractor(r"new\s+orders"),
    "shipments":            _index_extractor(r"shipments"),
    "employment":           _index_extractor(r"employment"),
}


def _try_float(s):
    try: return float(s)
    except (ValueError, TypeError): return None


def parse_html(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = _html_to_text(raw)
    out: dict = {}
    for name, rx in _INDEX_RX.items():
        m = rx.search(text)
        out[f"{name}_index_current"] = _try_float(m.group(1)) if m else None

    # Direction from general_activity sign
    ga = out["general_activity_index_current"]
    if ga is None:
        out["direction"] = None
    elif ga > 0:
        out["direction"] = "expanding"
    elif ga < 0:
        out["direction"] = "contracting"
    else:
        out["direction"] = "neutral"

    # Find the main report body: text between "Texas factory" (or
    # "production index, a key measure") and a footer marker.
    body_m = re.search(
        r"(production\s+index,?\s+a\s+key\s+measure[^.]{0,800}\.[^.]{0,2500}\.)",
        text, re.I | re.S,
    )
    out["narrative_verbatim"] = body_m.group(1) if body_m else None

    # Short summary attempt — take first 1200 chars of the narrative
    out["summary_verbatim"] = (out["narrative_verbatim"] or "")[:1500] or None
    return out
