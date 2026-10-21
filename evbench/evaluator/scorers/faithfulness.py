"""Report Faithfulness (FActScore-style atomic-fact verification).

Decompose the agent's report into atomic facts; verify each against the
tiered source hierarchy (keypoints / scenario context / external).


Two cost-reducing optimisations (2026-05-19):

  1. **Decompose quality + cap** — the prompt asks for ≤MAX_FACTS atomic
     scalar claims, skipping markdown headers / hedges / rhetorical
     sentences. We also drop fragments shorter than MIN_FACT_CHARS and
     truncate to MAX_FACTS post-hoc in case the LLM ignored the cap.
     This eliminates the pathological "108-fact" pattern seen earlier
     and cuts the per-period verify count.

  2. **Tier1 deterministic pre-match** — if the fact text contains a
     keypoint's literal GT value verbatim (numbers, named entities,
     enum tokens), it is grounded in keypoints by construction. Skip
     the per-fact LLM verify call and mark `tier1_supported` directly.
     Empirically covers ~25-35% of atomic facts on healthy reports
     (saves that fraction of LLM calls on the most expensive axis).
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..judge import Judge, parse_json_maybe
from ..schemas import AxisScore, RunRecord, ScenarioDef


# Hyperparameters for decompose quality. Conservative defaults; tune if the
# average atomic_facts/report drops below 5 (likely too aggressive) or stays
# above 20 (cap not enforced by LLM).
MAX_FACTS = 10
MIN_FACT_CHARS = 18    # after markdown stripping; below this is almost always junk

_MARKDOWN_PREFIX_RE = re.compile(r"^\s*(?:#{1,6}\s+|[*\-•]\s+)")
_MARKDOWN_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_TRAILING_TRUNCATED_WORD_RE = re.compile(r"\b\w{1,2}\s*$")   # ends in "U", "S", etc.
_LOOKS_LIKE_HEADER = re.compile(r"^[#*\-•]+\s*$")            # markers-only


def _strip_markdown(s: str) -> str:
    """Light markdown normalisation for fact-quality filtering.

    - Drop leading `#`, `*`, `-`, `•` prefixes (markdown headers + bullets).
    - Unwrap `**bold**` → `bold` (keeps text, drops marker).
    Whitespace is collapsed.
    """
    s = _MARKDOWN_PREFIX_RE.sub("", s)
    s = _MARKDOWN_BOLD_RE.sub(r"\1", s)
    return s.strip()


def _clean_facts(facts: list[str]) -> list[str]:
    """Post-process LLM-returned atomic-fact list:
       - strip whitespace + markdown wrappers
       - drop entries shorter than MIN_FACT_CHARS after stripping
       - drop markdown-marker-only lines
       - drop entries whose final word is 1-2 chars (typical truncation
         artifact from the fallback "split-by-period" decompose, e.g.
         "March 2024 U" from a "U.S." mid-sentence)
       - dedupe (case-insensitive, first occurrence wins)
       - cap at MAX_FACTS
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in facts:
        s = _strip_markdown(str(raw))
        if not s or _LOOKS_LIKE_HEADER.match(s):     continue
        if len(s) < MIN_FACT_CHARS:                  continue
        # "U", "S", "ends in U" — the fallback splitter on "U.S." produces these.
        if _TRAILING_TRUNCATED_WORD_RE.search(s):    continue
        key = s.lower()
        if key in seen:                              continue
        seen.add(key)
        out.append(s)
        if len(out) >= MAX_FACTS:                    break
    return out


def _decompose(judge: Judge, report: str) -> list[str]:
    """Ask the judge to extract ≤MAX_FACTS atomic, verifiable claims.

    Prompt is tightened from the original "one per sentence fragment" wording
    which produced 108-fact outputs on long reports. We now require single
    scalar claims (one number / entity / date / direction per fact) and
    explicitly tell the LLM to skip markdown headers, hedges, rhetorical
    sentences, and definitional preambles.
    """
    prompt = (
        f"Decompose this report into AT MOST {MAX_FACTS} atomic, verifiable "
        f"claims. Each claim must be ONE scalar fact: one number, one named "
        f"entity, one date, one direction, one classification — never a "
        f"compound sentence with multiple facts.\n"
        f"\n"
        f"Skip: markdown headers, bullet labels, rhetorical sentences, "
        f"hedges ('appears to be', 'broadly speaking'), and definitional "
        f"preambles. Each claim should be standalone (readable without the "
        f"surrounding report) and grounded enough to verify against a data "
        f"source.\n"
        f"\n"
        f"Return a JSON list of strings, no prose around it.\n"
        f"\n"
        f"Report:\n{report}\n"
    )
    res = judge.judge(prompt, reference=report[:200], kind="decompose")
    parsed = parse_json_maybe(res.text)
    if isinstance(parsed, list):
        return _clean_facts([str(x) for x in parsed])
    # Fallback: sentence-terminator split. Cleaning will drop most of the noise
    # that this fallback produces (markdown headers, single-letter shards).
    # Split only where a terminator is followed by whitespace and a capital,
    # so "87.5%" and "the U.S. load factor" stay inside their sentence.
    fallback = [s.strip() for s in re.split(r"(?<=[.;!?])\s+(?=[A-Z])", report)
                if s.strip()]
    return _clean_facts(fallback)


# ---------------------------------------------------------------------------
# Tier1 deterministic pre-match
# ---------------------------------------------------------------------------

def _gt_literal_forms(v: Any) -> list[str]:
    """All literal string forms of a GT value worth substring-searching.

    Returns lowercased fragments ≥4 chars (anything shorter is too common to
    be a reliable signal — e.g. "5", "us"). For numerics, includes integer
    form, .0 / .00 forms, and thousands-separator forms.
    """
    if v is None or isinstance(v, bool):
        return []
    out: set[str] = set()
    if isinstance(v, (int, float)):
        f = float(v)
        if f.is_integer():
            i = int(f)
            out.add(str(i))
            if abs(i) >= 1000:
                out.add(f"{i:,}")              # 6180 → "6,180"
        out.add(str(v))                         # "6180.0" or "6180"
        out.add(f"{f:.1f}")
        out.add(f"{f:.2f}")
        if abs(f) >= 1000:
            out.add(f"{f:,.1f}")
            out.add(f"{f:,.0f}")
    elif isinstance(v, str):
        out.add(v.strip())
    elif isinstance(v, list):
        for item in v:
            out.update(_gt_literal_forms(item))
    return [s.lower() for s in out if isinstance(s, str) and len(s) >= 4]


def _quick_tier1_match(fact: str, gt: dict) -> bool:
    """Deterministic tier1 check: fact contains a GT value verbatim.

    Returns True iff at least one literal form of one GT value appears as
    a substring of the fact (case-insensitive). Skip LLM verify in that
    case — the fact is grounded by definition.

    Note: GT values can sit nested in dicts (e.g. {"value": 7.5}). We
    only check the top-level dict here; richer scenarios may want to
    flatten before passing.
    """
    if not isinstance(gt, dict) or not fact:
        return False
    fact_lo = fact.lower()
    for v in gt.values():
        for form in _gt_literal_forms(v):
            if form in fact_lo:
                return True
    return False


def _build_reference_block(scenario: ScenarioDef, gt: dict,
                           context_excerpts: list[str]) -> str:
    """Compose the reference text passed to the judge for per-fact verification."""
    parts = []
    if scenario.faithfulness_sources.tier1_keypoints:
        kp_lines = []
        for kp in scenario.keypoints:
            val = gt.get(kp.answer_field) if kp.answer_field else None
            kp_lines.append(f"- {kp.id}: {kp.description}  value={val!r}")
        parts.append("[TIER 1 — Keypoints]\n" + "\n".join(kp_lines))
    if context_excerpts:
        parts.append("[TIER 2 — Scenario context]\n" + "\n".join(context_excerpts))
    return "\n\n".join(parts)


def _verify(judge: Judge, fact: str, reference: str,
            allow_tier3: bool) -> dict:
    tier3_clause = (
        "tier3_general_knowledge (only if the claim is encyclopedic and not "
        "contradicting any reference); "
    ) if allow_tier3 else ""
    # A claim like "YoY change was +4.13%" is supported only if the reference
    # rows actually give that number, so the judge must recompute it; this
    # needs a judge that reasons (see the `verify` entry of judge.by_kind).
    prompt = (
        "Verify a single atomic factual claim against reference sources.\n\n"
        f"Claim: {fact}\n\n"
        f"Reference sources:\n{reference}\n\n"
        "If the claim states a value computed from the reference data (a change, "
        "percentage, ratio, average, rank, maximum), recompute it from the "
        "reference rows first; a mismatch beyond rounding is a contradiction.\n"
        "Pick exactly one verdict from this set: "
        "tier1_supported (keypoint says so), "
        "tier2_supported (context says so), "
        f"{tier3_clause}"
        "contradicts_keypoint (clearly conflicts with a keypoint or with the "
        "reference data), "
        "speculation (unsupported by any reference).\n"
        'Return JSON: {"verdict": "<one>"}'
    )
    res = judge.judge(prompt, reference=reference[:400], kind="verify")
    parsed = parse_json_maybe(res.text)
    if isinstance(parsed, dict) and "verdict" in parsed:
        return parsed
    text = res.text.lower()
    for v in ("tier1_supported", "tier2_supported", "tier3_general_knowledge",
              "contradicts_keypoint", "speculation"):
        if v in text:
            return {"verdict": v}
    return {"verdict": "speculation"}


def _verdict_weight(v: str) -> float:
    """Binary verdict weights:

    Any verdict that says the claim IS supported by SOMETHING (keypoint,
    context, or general knowledge) → 1.0.
    Any verdict that says the claim is unsupported or contradicts the
    reference → 0.0.

    Rationale: under the previous scheme, `contradicts_keypoint` carried a
    -1.0 penalty that could push raw < 0 (then clamped to 0). Per-fact
    detail still records the contradiction verbatim, so the signal isn't
    lost — only its arithmetic effect on the aggregate is removed. Score
    is now strictly the fraction of atomic facts that are grounded.
    """
    return {
        "tier1_supported":          1.0,
        "tier2_supported":          1.0,
        "tier3_general_knowledge":  1.0,
        "speculation":              0.0,
        "contradicts_keypoint":     0.0,
    }.get(v, 0.0)


def score(run: RunRecord, scenario: ScenarioDef,
          gt: dict, judge: Judge,
          context_excerpts: list[str] | None = None) -> AxisScore:
    atomic_facts = _decompose(judge, run.report)
    if not atomic_facts:
        return AxisScore(name="report_faithfulness", value=None,
                         status="skipped", detail={"reason": "no_atomic_facts"})
    reference = _build_reference_block(scenario, gt, context_excerpts or [])
    allow_tier3 = scenario.faithfulness_sources.tier3_external
    per_fact: list[dict] = []
    tally = {"tier1_supported": 0, "tier2_supported": 0,
             "tier3_general_knowledge": 0,
             "speculation": 0, "contradicts_keypoint": 0}
    score_sum = 0.0
    # Track quick-match savings so we can report them in score_record.detail.
    n_quick = 0
    n_llm = 0
    for f in atomic_facts:
        if _quick_tier1_match(f, gt):
            verdict = "tier1_supported"
            entry = {"fact": f, "verdict": verdict, "via": "quick_match"}
            n_quick += 1
        else:
            v = _verify(judge, f, reference, allow_tier3)
            verdict = v.get("verdict", "speculation")
            entry = {"fact": f, "verdict": verdict, "via": "llm"}
            n_llm += 1
        tally[verdict] = tally.get(verdict, 0) + 1
        score_sum += _verdict_weight(verdict)
        per_fact.append(entry)
    # Normalize to [0, 100]; allow raw score to drop below 0 if contradicted, then clamp
    raw = (score_sum / max(1, len(atomic_facts))) * 100
    value = max(0.0, min(100.0, raw))
    return AxisScore(
        name="report_faithfulness",
        value=round(value, 2),
        status="scored",
        detail={
            "atomic_facts":      per_fact,
            "tier_distribution": tally,
            "raw_score":         round(raw, 2),
            "n_facts":           len(atomic_facts),
            "n_quick_match":     n_quick,
            "n_llm_verify":      n_llm,
            "llm_calls_saved":   n_quick,    # vs the no-pre-match baseline
        },
    )
