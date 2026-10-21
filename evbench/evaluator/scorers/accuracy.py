"""Keypoint Accuracy scorer.

Compares the agent's structured_answer with GT, field by field, for every
keypoint that has an `answer_field`. Deterministic: no judge call. Keypoints
without an answer field are about the report's content and are scored only
by the coverage axis.

"""
from __future__ import annotations

from typing import Any

from ..judge import Judge
from ..schemas import AxisScore, Keypoint, RunRecord, ScenarioDef


def _match_enum(a: Any, b: Any) -> float:
    return 1.0 if a == b else 0.0


def _match_numeric(a: Any, b: Any, abs_tol: float | None, rel_tol: float | None) -> float:
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return 0.0
    if abs_tol is not None and abs(fa - fb) <= abs_tol:
        return 1.0
    if rel_tol is not None and fb != 0 and abs(fa - fb) / abs(fb) <= rel_tol:
        return 1.0
    if abs_tol is None and rel_tol is None and fa == fb:
        return 1.0
    return 0.0


def _match_string_set(a: Any, b: Any) -> float:
    if not isinstance(a, list) or not isinstance(b, list):
        return 0.0
    sa, sb = set(map(str, a)), set(map(str, b))
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return (2 * inter) / (len(sa) + len(sb))


def _match_boolean(a: Any, b: Any) -> float:
    return 1.0 if bool(a) == bool(b) else 0.0


def _match_string(a: Any, b: Any) -> float:
    if not isinstance(a, str) or not isinstance(b, str):
        return 0.0
    return 1.0 if a.strip() == b.strip() else 0.0


def _match(a: Any, b: Any, kp: Keypoint) -> float:
    if kp.answer_type == "enum":
        return _match_enum(a, b)
    if kp.answer_type in ("numeric", "number"):
        return _match_numeric(a, b, kp.tolerance_abs, kp.tolerance_rel)
    if kp.answer_type in ("string_set", "list"):
        return _match_string_set(a, b)
    if kp.answer_type == "boolean":
        return _match_boolean(a, b)
    # "string" / "free_text" / unknown — fall through to lenient string compare.
    return _match_string(a, b)


def score(run: RunRecord, scenario: ScenarioDef,
          gt: dict, judge: Judge) -> AxisScore:
    """`judge` is unused; the signature matches the other axes."""
    per_kp: list[dict] = []
    for kp in scenario.keypoints:
        if kp.answer_field is None:
            continue                    # report-only: the coverage axis's job
        agent_val = run.structured_answer.get(kp.answer_field)
        gt_val = gt.get(kp.answer_field)
        per_kp.append({"id": kp.id,
                       "question_tag": kp.question_tag,
                       "agent_value": agent_val,
                       "gt_value": gt_val,
                       "score": _match(agent_val, gt_val, kp)})
    if not per_kp:
        return AxisScore(name="keypoint_accuracy", value=None, status="skipped",
                         detail={"reason": "no keypoint has an answer_field"})
    # Unweighted mean: every keypoint counts the same.
    value = sum(k["score"] for k in per_kp) / len(per_kp)
    return AxisScore(name="keypoint_accuracy", value=round(value * 100, 2),
                     status="scored", detail={"per_kp": per_kp})
