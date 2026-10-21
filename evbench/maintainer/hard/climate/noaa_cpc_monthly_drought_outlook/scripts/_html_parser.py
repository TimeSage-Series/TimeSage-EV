"""Parse a NOAA CPC Monthly Drought Outlook narrative file into the
structured Hard-tier categorical fields needed by the answer schema.

The CPC MDO is published as a plain ASCII narrative (with optional html
wrapper) at:

    https://www.cpc.ncep.noaa.gov/products/expert_assessment/MDO/
        archives/<YYYY>/<MM>/mdo_<mon><yy>_text.txt

The narrative is a sequence of region-level paragraphs. Each paragraph
discusses one CONUS sub-region (or Hawaii / Alaska / Puerto Rico) and
applies one or more of the categorical labels:

    persists | develops | expansion | intensification | improves | eased | removes

Plus driver sentences (precipitation forecast, soil moisture, snowmelt,
ENSO state) and uncertainty sentences ("low confidence", "uncertainty",
"may", "could").

This parser is regex/keyword-driven against the raw text. We do NOT
require valid HTML — many issues are served as text/plain. If the file
is wrapped in HTML we strip tags first.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Optional

# -------------------------------------------------------------------- I/O

def read_mdo_text(path: Path) -> str:
    """Read an MDO source file (.html or .txt) and return clean text."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    # Strip HTML tags if any
    no_tags = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    no_tags = re.sub(r"<style[\s\S]*?</style>", " ", no_tags, flags=re.I)
    no_tags = re.sub(r"<[^>]+>", " ", no_tags)
    # Normalize whitespace and entities
    no_tags = no_tags.replace("&nbsp;", " ").replace("&amp;", "&")
    no_tags = no_tags.replace("&lt;", "<").replace("&gt;", ">")
    no_tags = re.sub(r"[ \t]+", " ", no_tags)
    no_tags = re.sub(r"\n{3,}", "\n\n", no_tags)
    return no_tags.strip()


# -------------------------------------------------------------------- regions

# Pattern -> canonical region label. Order matters: longest match first
# so we don't match "Plains" before "Northern Plains".
REGION_PATTERNS = [
    ("Pacific Northwest",   re.compile(r"\bPacific\s+Northwest\b", re.I)),
    ("Northern Plains",     re.compile(r"\b(Northern\s+(?:Great\s+)?Plains|Northern\s+Rockies)\b", re.I)),
    ("Southern Plains",     re.compile(r"\b(Southern\s+(?:Great\s+)?Plains|Texas|Oklahoma)\b", re.I)),
    ("Southwest",           re.compile(r"\b(Southwest|Arizona|New\s+Mexico|Great\s+Basin|California|Nevada|Four\s+Corners)\b", re.I)),
    ("Midwest",             re.compile(r"\b(Midwest|Ohio\s+Valley|Upper\s+Mississippi|Iowa|Missouri|Illinois|Indiana)\b", re.I)),
    ("Northeast",           re.compile(r"\b(Northeast|New\s+England|Mid[- ]?Atlantic|New\s+York|Pennsylvania)\b", re.I)),
    ("Southeast",           re.compile(r"\b(Southeast|Florida|Georgia|Alabama|Carolinas?|Tennessee|Gulf\s+Coast)\b", re.I)),
    ("Hawaii",              re.compile(r"\bHawaii\b", re.I)),
    ("Alaska",              re.compile(r"\bAlaska\b", re.I)),
    ("Puerto Rico",         re.compile(r"\b(Puerto\s+Rico|U\.?S\.?\s+Virgin\s+Islands|USVI)\b", re.I)),
]

# Sentence-level outcome triggers.
# A region landing in `regions_X` requires that an outcome word from set X
# appears in the same sentence (or adjacent sentence) as the region.
OUTCOME_TRIGGERS = {
    "persists":  re.compile(
        r"\b(persist(?:s|ence|ing)?|continues?(?:\s+to\s+exist)?|remains?|"
        r"is\s+expected\s+to\s+(?:continue|persist)|no\s+drought\s+relief)\b",
        re.I),
    "develops":  re.compile(
        r"\b(develop(?:s|ment|ing)?|onset|new\s+drought|emerge(?:s|nce|nt)?|"
        r"expansion|expanding|intensif(?:y|ies|ying|ication))\b",
        re.I),
    "improves":  re.compile(
        r"\b(improve(?:s|ment|d)?|some\s+improvement|improvement\s+likely|"
        r"easing|eased|reduc(?:e|ed|tion)|wetter|near\s+to\s+above\-?normal)\b",
        re.I),
    "removes":   re.compile(
        r"\b(remov(?:al|ed|es)|drought\s+(?:relief|removal)|end(?:s|ing)?\s+(?:of\s+)?drought|"
        r"removed?\s+by|elimination)\b",
        re.I),
}


def _split_sentences(text: str) -> list[str]:
    # Crude sentence splitter that respects common abbreviations
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text)
    return [p.strip() for p in parts if p.strip()]


def _region_in_sentence(sent: str) -> set[str]:
    regions: set[str] = set()
    for canon, rx in REGION_PATTERNS:
        if rx.search(sent):
            regions.add(canon)
    return regions


def classify_regions(text: str) -> dict[str, list[str]]:
    """Walk the narrative sentence-by-sentence and bucket each region
    into one of the four categorical outcomes.

    Decision rule:
      * For each sentence, identify the regions and the outcome triggers
        present.
      * If a sentence contains region(s) and exactly one outcome trigger,
        assign each region to that bucket.
      * If a sentence has region(s) but no outcome trigger, fall through
        to the next sentence (a follow-up sentence often carries the
        verb). Maintain a sliding 1-sentence context window.
      * If multiple outcome triggers appear, prefer 'removes' > 'improves'
        > 'develops' > 'persists' (most-decisive wins) UNLESS a clear
        contrast word ('but', 'however', 'although', 'while') splits the
        sentence — in which case we take the trigger from the half that
        contains the region.
      * Each region is assigned to AT MOST one bucket per issue (the
        most recent assignment wins).
    """
    buckets: dict[str, list[str]] = {
        "persists": [],
        "develops": [],
        "improves": [],
        "removes":  [],
    }
    region_assignment: dict[str, str] = {}

    sentences = _split_sentences(text)
    prev_regions: set[str] = set()
    for sent in sentences:
        regions = _region_in_sentence(sent)
        triggers_hit = {
            name: bool(rx.search(sent))
            for name, rx in OUTCOME_TRIGGERS.items()
        }
        outcomes_in_sent = [name for name, hit in triggers_hit.items() if hit]
        target_regions = regions if regions else prev_regions
        if not target_regions or not outcomes_in_sent:
            prev_regions = regions or prev_regions
            continue

        outcome = _pick_outcome(sent, outcomes_in_sent)
        for r in target_regions:
            region_assignment[r] = outcome
        prev_regions = regions or prev_regions

    for region, outcome in region_assignment.items():
        buckets[outcome].append(region)
    for k in buckets:
        buckets[k] = sorted(set(buckets[k]))
    return buckets


def _pick_outcome(sent: str, hits: list[str]) -> str:
    """Pick the most-decisive outcome present in a sentence.

    Tie-breaker: removes > improves > develops > persists.
    Contrast words flip emphasis to the later clause.
    """
    priority = {"removes": 4, "improves": 3, "develops": 2, "persists": 1}
    contrast_split = re.split(r"\b(?:but|however|although|while|though)\b", sent, maxsplit=1, flags=re.I)
    if len(contrast_split) == 2:
        # Prefer triggers from the second half
        second_hits = [
            name for name in hits
            if OUTCOME_TRIGGERS[name].search(contrast_split[1])
        ]
        if second_hits:
            return max(second_hits, key=lambda n: priority[n])
    return max(hits, key=lambda n: priority[n])


# -------------------------------------------------------------------- drivers

DRIVER_PATTERNS = {
    "precipitation outlook": re.compile(
        r"\b(precipitation\s+(?:outlook|forecast|amounts?)|above[- ]?normal\s+precipitation|"
        r"below[- ]?normal\s+precipitation|wet\s+pattern|dry\s+pattern|rain(?:fall|y\s+season)?)\b",
        re.I),
    "soil moisture": re.compile(
        r"\b(soil\s+moisture|soil\s+conditions?|antecedent\s+(?:soil|moisture))\b",
        re.I),
    "snowmelt / snowpack": re.compile(
        r"\b(snow(?:pack|melt)?|snow[- ]?water\s+equivalent|SWE\b)\b",
        re.I),
    "ENSO state": re.compile(
        r"\b(ENSO|El\s+Ni[ñn]o|La\s+Ni[ñn]a|ENSO[- ]?neutral)\b",
        re.I),
    "temperature outlook": re.compile(
        r"\b(temperature\s+(?:outlook|forecast)|above[- ]?normal\s+temperatures?|warm\s+pattern)\b",
        re.I),
    "tropical / hurricane influence": re.compile(
        r"\b(tropical\s+(?:cyclone|storm|system)|hurricane(?:\s+season)?|landfall|Atlantic\s+hurricane)\b",
        re.I),
    "monsoon": re.compile(
        r"\b(monsoon|Southwest\s+monsoon)\b",
        re.I),
}


def extract_drivers(text: str) -> list[str]:
    """Return the canonical driver keys mentioned in the narrative."""
    hits = []
    for canon, rx in DRIVER_PATTERNS.items():
        if rx.search(text):
            hits.append(canon)
    return hits


# -------------------------------------------------------------------- evidence sentences

def extract_driver_sentences(text: str, limit: int = 10) -> list[str]:
    sents = _split_sentences(text)
    out: list[str] = []
    for s in sents:
        for rx in DRIVER_PATTERNS.values():
            if rx.search(s) and 40 < len(s) < 600:
                out.append(s)
                break
        if len(out) >= limit:
            break
    return out


UNCERTAINTY_TRIGGERS = re.compile(
    r"\b(uncertain(?:ty|ties)?|low\s+confidence|may|could|some\s+possibility|"
    r"forecaster\s+confidence|model\s+spread|caveats?|considerable\s+uncertainty)\b",
    re.I,
)


def extract_uncertainty_sentences(text: str, limit: int = 6) -> list[str]:
    sents = _split_sentences(text)
    out: list[str] = []
    for s in sents:
        if UNCERTAINTY_TRIGGERS.search(s) and 40 < len(s) < 600:
            out.append(s)
        if len(out) >= limit:
            break
    return out


# -------------------------------------------------------------------- header

HEADER_PATTERNS = [
    re.compile(r"Issued\s+on?\s*[:\-]?\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", re.I),
    re.compile(r"Valid\s+([A-Z][a-z]+\s+\d{1,2}\s*[\-–]\s*[A-Z][a-z]+\s+\d{1,2},\s+\d{4})", re.I),
]


def extract_header_metadata(text: str) -> dict[str, Optional[str]]:
    issued = None
    valid = None
    m = HEADER_PATTERNS[0].search(text)
    if m:
        issued = m.group(1)
    m = HEADER_PATTERNS[1].search(text)
    if m:
        valid = m.group(1)
    return {"issued": issued, "valid": valid}


# -------------------------------------------------------------------- main

def parse_mdo(path: Path) -> dict:
    text = read_mdo_text(path)
    buckets = classify_regions(text)
    return {
        "source_path":  str(path.name),
        "header":       extract_header_metadata(text),
        "regions_persists": buckets["persists"],
        "regions_develops": buckets["develops"],
        "regions_improves": buckets["improves"],
        "regions_removes":  buckets["removes"],
        "key_drivers":      extract_drivers(text),
        "driver_sentences": extract_driver_sentences(text),
        "uncertainty_sentences": extract_uncertainty_sentences(text),
        "narrative_excerpt": text[:3000],
    }
