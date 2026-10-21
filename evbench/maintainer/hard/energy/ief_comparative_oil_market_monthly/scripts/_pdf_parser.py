"""Parse IEF Comparative Analysis PDF — best-effort Hard-tier extraction."""
from __future__ import annotations
import re
from pathlib import Path
from pypdf import PdfReader

IEA_DEMAND_RX = re.compile(r"(?i)IEA[^.\n]{0,120}?(\d+\.\d+)\s*mb/d")
OPEC_DEMAND_RX = re.compile(r"(?i)OPEC[^.\n]{0,120}?(\d+\.\d+)\s*mb/d")
EIA_DEMAND_RX = re.compile(r"(?i)\bEIA\b[^.\n]{0,120}?(\d+\.\d+)\s*mb/d")
DIVERGENCE_KW = re.compile(r"(?i)(diverge|disagree|differ|spread|gap\s+between)")
CONSENSUS_KW = re.compile(r"(?i)(consensus|aligned|converg)")


def read_text(path: Path) -> str:
    r = PdfReader(str(path))
    parts = []
    for p in r.pages[:20]:
        try: parts.append(p.extract_text() or "")
        except: parts.append("")
    return "\n".join(parts)


def _to_float(s):
    try: return float(s)
    except: return None


def parse(path: Path) -> dict:
    text = read_text(path)
    out = {}
    for k, rx in [("iea_demand_forecast_mbd", IEA_DEMAND_RX),
                  ("opec_demand_forecast_mbd", OPEC_DEMAND_RX),
                  ("eia_demand_forecast_mbd", EIA_DEMAND_RX)]:
        m = rx.search(text); out[k] = _to_float(m.group(1)) if m else None

    vals = [v for v in (out["iea_demand_forecast_mbd"], out["opec_demand_forecast_mbd"],
                        out["eia_demand_forecast_mbd"]) if v is not None]
    out["consensus_range_mbd"] = (max(vals) - min(vals)) if len(vals) >= 2 else None
    out["divergence_keyword_count"] = len(DIVERGENCE_KW.findall(text))
    out["consensus_keyword_count"] = len(CONSENSUS_KW.findall(text))

    m = re.search(r"(?i)(Executive\s+Summary|Summary|Highlights|Overview)", text)
    out["executive_summary_text"] = (text[m.start():m.start()+3000] if m else text[:3000]).strip()

    out["divergence_drivers_text"] = "\n".join(re.findall(
        r"(?i)[^.\n]{0,250}(?:diverge|differ|spread)[^.\n]{0,250}\.", text)[:5])
    out["outlook_text"] = "\n".join(re.findall(
        r"(?i)[^.\n]{0,250}(?:expected|forecast|in the coming|outlook)[^.\n]{0,250}\.", text)[:5])
    return out
