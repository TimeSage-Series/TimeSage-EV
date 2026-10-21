"""Parse an ECDC CDTR PDF into structured digest fields (Middle-tier).

Strategy: count keyword occurrences per canonical threat. A threat counts as
'present in a dedicated section' when its keyword density crosses a
threshold (default 8). The threat with the highest density in a given issue
is the 'leading_topic'. This is far more robust across CDTR's heterogeneous
PDF formatting than trying to detect section headers.

We also extract the verbatim 'Executive summary' block where present, to
serve as the reference for grading the agent's `report`.
"""
from __future__ import annotations
import re
from pathlib import Path

from pypdf import PdfReader

# canonical threat -> list of keyword patterns (case-insensitive)
THREAT_KEYWORDS: dict[str, list[re.Pattern]] = {
    "h5n1":          [re.compile(r"H5N1", re.I)],
    "h9n2":          [re.compile(r"H9N2", re.I)],
    "h10n3":         [re.compile(r"H10N3", re.I)],
    "h7n9":          [re.compile(r"H7N9", re.I)],
    "mpox":          [re.compile(r"\bmpox\b", re.I), re.compile(r"monkeypox", re.I)],
    "measles":       [re.compile(r"\bmeasles\b", re.I)],
    "dengue":        [re.compile(r"\bdengue\b", re.I)],
    "west_nile":     [re.compile(r"\bwest\s+nile\b", re.I), re.compile(r"\bWNV\b")],
    "chikungunya":   [re.compile(r"\bchikungunya\b", re.I)],
    "cholera":       [re.compile(r"\bcholera\b", re.I)],
    "oropouche":     [re.compile(r"\boropouche\b", re.I)],
    "mers_cov":      [re.compile(r"\bMERS[-\s]?CoV\b", re.I), re.compile(r"Middle\s+East\s+respiratory", re.I)],
    "crimean_congo": [re.compile(r"Crimean[-\s]Congo", re.I), re.compile(r"\bCCHF\b")],
    "respiratory_overview": [re.compile(r"Overview\s+of\s+respiratory\s+virus\s+epidemiology", re.I)],
    "polio":         [re.compile(r"\bpolio\b", re.I), re.compile(r"poliovirus", re.I)],
    "salmonella":    [re.compile(r"\bsalmonella\b", re.I)],
    "ebola":         [re.compile(r"\bebola\b", re.I)],
    "marburg":       [re.compile(r"\bmarburg\b", re.I)],
    "hand_foot_mouth": [re.compile(r"hand,?\s*foot,?\s*and\s+mouth", re.I), re.compile(r"\bHFMD\b")],
    "hantavirus":    [re.compile(r"\bhantavirus\b", re.I)],
    "mass_gathering": [re.compile(r"\bmass\s+gathering(?:\s+monitoring)?\b", re.I)],
    "rabies":        [re.compile(r"\brabies\b", re.I)],
    "yellow_fever":  [re.compile(r"\byellow\s+fever\b", re.I)],
}

PRESENCE_THRESHOLD = 8   # min keyword hits to count as a dedicated section
EXEC_SUMMARY_HEADER = re.compile(r"(?i)Executive\s+summary")
TOPICS_HEADER = re.compile(r"(?i)This\s+week['']?s\s+topics")


def read_pdf_text(path: Path) -> str:
    r = PdfReader(str(path))
    return "\n".join(p.extract_text() or "" for p in r.pages)


def count_threats(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for label, patterns in THREAT_KEYWORDS.items():
        c = 0
        for rx in patterns:
            c += len(rx.findall(text))
        out[label] = c
    return out


def threats_present(counts: dict[str, int], threshold: int = PRESENCE_THRESHOLD) -> list[str]:
    return sorted([t for t, c in counts.items() if c >= threshold])


def leading_topic(counts: dict[str, int]) -> str | None:
    if not counts:
        return None
    best = max(counts.items(), key=lambda x: x[1])
    if best[1] < PRESENCE_THRESHOLD:
        return None
    return best[0]


def extract_executive_summary(text: str) -> str:
    """Return the verbatim executive summary block."""
    m = EXEC_SUMMARY_HEADER.search(text)
    if not m:
        return ""
    start = m.end()
    # Heuristic stop: a long block ends at the next "References" or "page" footer
    # or after about 4000 chars. We use 4000 as a hard cap.
    return text[start:start + 4000].strip()


def extract_topics_listed(text: str) -> list[str]:
    """Pull the topic lines below 'This week's topics' header. Best-effort."""
    m = TOPICS_HEADER.search(text)
    if not m:
        return []
    chunk = text[m.end():m.end() + 1500]
    topics: list[str] = []
    for line in chunk.split("\n"):
        line = line.strip()
        nm = re.match(r"^(\d+)\.\s+(.+)$", line)
        if nm:
            topics.append(nm.group(2).strip())
        elif topics and not line:
            break
    return topics


def parse_cdtr(path: Path) -> dict:
    text = read_pdf_text(path)
    counts = count_threats(text)
    present = threats_present(counts)
    return {
        "topics_listed":           extract_topics_listed(text),
        "threat_keyword_counts":   counts,
        "threats_present":         present,
        "n_threats_present":       len(present),
        "leading_topic":           leading_topic(counts),
        "executive_summary":       extract_executive_summary(text),
    }
