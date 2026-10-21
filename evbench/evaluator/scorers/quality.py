"""Report Quality scorer.

Tier-specific writing rubric. Deliberately decoupled from factual axes —
the prompt tells the judge not to penalize factual errors.

"""
from __future__ import annotations

from ..judge import Judge, parse_json_maybe
from ..schemas import AxisScore, RunRecord, ScenarioDef


def score(run: RunRecord, scenario: ScenarioDef,
          gt: dict, judge: Judge) -> AxisScore:
    rubric = scenario.quality_rubric
    req_block = "\n  - ".join(rubric.required_signals) or "(none declared)"
    forb_block = "\n  - ".join(rubric.forbidden_signals) or "(none declared)"
    exemplar = rubric.exemplar or "(no exemplar provided)"
    prompt = (
        "You are scoring a report's WRITING quality only — its genre conformance, "
        "structure, and readability. DO NOT score for factual correctness; that "
        "is evaluated separately by a different scorer.\n\n"
        f"Tier genre:\n  {rubric.genre}\n\n"
        f"Required signals (each contributes to score; PARTIAL ok):\n  - {req_block}\n\n"
        f"Forbidden signals (each present = penalty):\n  - {forb_block}\n\n"
        f"Exemplar of a good report:\n  {exemplar}\n\n"
        f"Report to score:\n{run.report}\n\n"
        'Return JSON: {"required_hits": ["<signal>", ...], '
        '"required_partial": ["<signal>", ...], '
        '"required_misses": ["<signal>", ...], '
        '"forbidden_violations": ["<signal>", ...], '
        '"rationale": "<one sentence>"}'
    )
    res = judge.judge(prompt, reference=rubric.genre, kind="quality")
    parsed = parse_json_maybe(res.text) or {}
    req = len(rubric.required_signals) or 1
    hits = len(parsed.get("required_hits") or [])
    partial = len(parsed.get("required_partial") or [])
    violations = len(parsed.get("forbidden_violations") or [])
    raw = ((hits + 0.5 * partial - violations) / req) * 100
    value = max(0.0, min(100.0, raw))
    return AxisScore(
        name="report_quality",
        value=round(value, 2),
        status="scored",
        detail={
            "required_hits":         parsed.get("required_hits") or [],
            "required_partial":      parsed.get("required_partial") or [],
            "required_misses":       parsed.get("required_misses") or [],
            "forbidden_violations":  parsed.get("forbidden_violations") or [],
            "rationale":             parsed.get("rationale") or "",
            "raw_score":             round(raw, 2),
        },
    )
