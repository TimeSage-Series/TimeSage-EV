"""Keypoint Coverage (Pyramid / ACU recall).

For each predefined keypoint, judge "does this report communicate it?"
Score = recall, the unweighted mean over keypoints.


Optimisation (2026-05-19, parity with faithfulness): if a keypoint has
an `answer_field`, and the report contains the corresponding GT scalar
value verbatim (using `_gt_literal_forms` from faithfulness), we mark
the keypoint as covered (1.0) WITHOUT an LLM call.

Tier gate: applied ONLY to `easy` and `middle` scenarios. Empirical
agreement with the LLM on those is 100% (easy) / ~95% (middle, after
removing API-failure noise). On `hard` tier, ~11% of value-present
cases got LLM=NO — those reports mention the GT scalar tangentially
without truly communicating the keypoint's conceptual meaning. We
keep hard tier on the full LLM path to avoid that false-positive.

Report-only keypoints (answer_field=None) always go through the LLM
because they aren't tied to a single GT scalar.
"""
from __future__ import annotations

from ..judge import Judge
from ..schemas import AxisScore, Keypoint, RunRecord, ScenarioDef
from .faithfulness import _gt_literal_forms


def _quick_coverage_match(report: str, kp: Keypoint, gt: dict) -> bool:
    """Deterministic coverage check: does the report contain this keypoint's
    GT scalar verbatim?

    Only meaningful when:
      * keypoint has an `answer_field` (i.e., it anchors to a single GT
        scalar — report-only keypoints don't),
      * the GT value at that field has at least one literal form ≥4 chars
        (numbers ≥4 digits + decimals, names ≥4 chars, list items).

    Returns False otherwise → caller falls back to LLM judge.
    """
    if not kp.answer_field or not report:
        return False
    val = gt.get(kp.answer_field)
    if val is None:
        return False
    report_lo = report.lower()
    for form in _gt_literal_forms(val):
        if form in report_lo:
            return True
    return False


def _coverage_for_kp(judge: Judge, report: str, kp: Keypoint) -> float:
    prompt = (
        "You are checking whether a report communicates a predefined content unit "
        "(ACU). Reply with exactly one of: YES, PARTIAL, NO.\n\n"
        f"Content unit:\n  description: {kp.description}\n"
        f"  verification question: {kp.verification_question}\n\n"
        f"Report:\n{report}\n\n"
        "Reply with the single word YES, PARTIAL, or NO and nothing else."
    )
    res = judge.judge(prompt, reference=kp.description, kind="coverage")
    txt = res.text.strip().upper()
    if txt.startswith("YES"):
        return 1.0
    if txt.startswith("PARTIAL"):
        return 0.5
    return 0.0


QUICK_MATCH_TIERS = {"easy", "middle"}   # hard stays on full LLM (see docstring)


def score(run: RunRecord, scenario: ScenarioDef,
          gt: dict, judge: Judge) -> AxisScore:
    per_kp: list[dict] = []
    n_quick = 0
    n_llm = 0
    tier_allows_quick = (scenario.tier in QUICK_MATCH_TIERS)
    for kp in scenario.keypoints:
        if tier_allows_quick and _quick_coverage_match(run.report, kp, gt):
            hit = 1.0
            via = "quick_match"
            n_quick += 1
        else:
            hit = _coverage_for_kp(judge, run.report, kp)
            via = "llm"
            n_llm += 1
        per_kp.append({"id": kp.id, "coverage": hit, "via": via})
    value = (sum(k["coverage"] for k in per_kp) / len(per_kp)) if per_kp else 0.0
    return AxisScore(
        name="keypoint_coverage",
        value=round(value * 100, 2),
        status="scored",
        detail={
            "per_kp": per_kp,
            "n_keypoints":      len(scenario.keypoints),
            "n_quick_match":    n_quick,
            "n_llm_verify":     n_llm,
            "llm_calls_saved":  n_quick,
        },
    )
