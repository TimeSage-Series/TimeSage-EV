"""Build EpisodeTurn feedback from a scored run, to be fed back to the
agent on the next turn of an episode.

Three feedback modes, ranked by information density:

  none      — aggregate + passed only
  score     — + per-axis scores + per-keypoint pass/fail with values
  detailed  — + judge atomic-fact verdicts + quality rubric breakdown

The runner enforces the temporal invariant: build_feedback() is only called
for periods strictly < the period the agent is about to brief on. Within
that constraint, exposing the GT for already-scored periods is legitimate
— analysts in real life do learn whether their prior briefing was right.

`EpisodeTurn.rendered` is **markdown**: numbered per-keypoint feedback for
GT-anchored items (agent_value vs gt_value) and per-dimension feedback for
judge-evaluated items, with a natural-language preamble telling the agent
the feedback comes from comparison against real reference data.

"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from .protocol import EpisodeTurn

FeedbackMode = Literal["none", "score", "detailed"]


# Stable axis display order, used by both the summary and the judge section.
_KEYPOINT_AXES = ("keypoint_accuracy", "keypoint_coverage")
_JUDGE_AXES = (
    ("report_faithfulness", "Report faithfulness"),
    ("report_quality",      "Report quality"),
)


def _axis_value(scores: dict, name: str) -> float | None:
    rec = scores.get(name)
    if not rec:
        return None
    v = rec.get("value")
    return float(v) if v is not None else None


def _kp_records(scores: dict) -> list[dict]:
    """Merge keypoint_accuracy.per_kp + keypoint_coverage.per_kp into a
    single list keyed by kp id.

    A keypoint with an answer field passes on accuracy; a report-only one
    (absent from accuracy) passes on coverage."""
    by_id: dict[str, dict] = {}
    acc = (scores.get("keypoint_accuracy") or {}).get("detail") or {}
    cov = (scores.get("keypoint_coverage") or {}).get("detail") or {}
    for r in acc.get("per_kp", []):
        by_id.setdefault(r["id"], {"id": r["id"]}).update({
            "passed":      float(r.get("score") or 0.0) >= 0.99,
            "accuracy":    r.get("score"),
            "agent_value": r.get("agent_value"),
            "gt_value":    r.get("gt_value"),
            "question_tag": r.get("question_tag"),
        })
    for r in cov.get("per_kp", []):
        rec = by_id.setdefault(r["id"], {"id": r["id"]})
        rec["coverage"] = r.get("coverage")
        rec.setdefault("passed", float(r.get("coverage") or 0.0) >= 0.99)
    return list(by_id.values())


def _faithfulness_notes(scores: dict) -> list[str]:
    rec = (scores.get("report_faithfulness") or {}).get("detail") or {}
    notes: list[str] = []
    facts = rec.get("atomic_facts") or []
    for f in facts:
        verdict = f.get("verdict", "")
        if verdict in {"speculation", "contradicts_keypoint",
                       "tier3_general_knowledge"}:
            notes.append(f"{verdict}: {f.get('fact','')[:160]}")
    return notes


def build_feedback(*, period: str, run_record: dict, score_record: dict,
                   scenario_dir: Path,
                   mode: FeedbackMode = "score") -> EpisodeTurn:
    """Produce one EpisodeTurn worth of feedback for `period`."""
    aggregate = float(score_record.get("aggregate") or 0.0)
    passed    = bool(score_record.get("passed") or False)
    sa        = dict(run_record.get("structured_answer") or {})
    scores    = dict(score_record.get("scores") or {})

    axis_scores: dict[str, float] = {}
    for axis_name in ("keypoint_accuracy", "keypoint_coverage",
                      "report_faithfulness", "report_quality"):
        v = _axis_value(scores, axis_name)
        if v is not None:
            axis_scores[axis_name] = v

    kp_full = _kp_records(scores) if mode != "none" else []
    if mode == "score":
        kp_results = [{"id": k["id"], "passed": k.get("passed", False)}
                      for k in kp_full]
        faithfulness_notes: list[str] = []
    elif mode == "detailed":
        kp_results = []
        for k in kp_full:
            entry = {"id": k["id"], "passed": k.get("passed", False)}
            if not entry["passed"]:
                entry["agent_value"] = k.get("agent_value")
                entry["gt_value"]    = k.get("gt_value")
            kp_results.append(entry)
        faithfulness_notes = _faithfulness_notes(scores)
    else:
        kp_results = []
        faithfulness_notes = []

    rendered = _render_markdown(
        period=period, run_record=run_record, score_record=score_record,
        mode=mode,
    )

    return EpisodeTurn(
        period=period,
        aggregate=aggregate,
        passed=passed,
        axis_scores=axis_scores,
        structured_answer=sa,
        keypoint_results=kp_results,
        faithfulness_notes=faithfulness_notes,
        rendered=rendered,
    )


def render_scoring_unavailable(period: str, reason: str) -> str:
    """Markdown stub when scoring failed/was skipped — still informs the agent."""
    return (
        f"## ⚠️ Period {period} — scoring unavailable\n\n"
        f"Your previous period's submission could not be scored "
        f"automatically (`{reason}`). Continue with the next period as best "
        f"you can, but do not assume the previous answer was correct."
    )


def _fmt_value(v: Any) -> str:
    """Pretty-print a kp value for inline markdown. Truncates long blobs."""
    if v is None:
        return "(no value)"
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, dict)):
        s = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    else:
        s = str(v)
    return s if len(s) <= 200 else s[:200] + "…"


def _render_markdown(*, period: str, run_record: dict, score_record: dict,
                     mode: FeedbackMode = "score") -> str:
    """Build the markdown feedback string shown to the agent before the
    next period. Two main sections:

      1. Keypoint-by-keypoint (numbered, with agent_value vs gt_value
         when the keypoint anchors to a structured answer field)
      2. Judge-evaluated dimensions (numbered, per axis, with notes)

    A natural-language preamble tells the agent this feedback is based
    on comparison against real reference data and an automated judge.
    """
    aggregate    = score_record.get("aggregate")
    passed       = bool(score_record.get("passed") or False)
    scores       = dict(score_record.get("scores") or {})
    failure_mode = score_record.get("failure_mode")

    lines: list[str] = []

    # 1. Preamble — natural language, not a bullet
    lines.append(
        f"The block below is **scored feedback on your previous period "
        f"({period})**, produced by checking your structured answer against "
        f"the reference ground truth and by an automated judge evaluating "
        f"your report. Read it before answering this period — for each "
        f"numbered keypoint that did not pass, the correct value is shown "
        f"so you can calibrate your method."
    )
    lines.append("")

    # 2. Score summary
    lines.append(f"## 📊 Score summary — period {period}")
    lines.append("")
    if isinstance(aggregate, (int, float)):
        verdict = "**PASSED**" if passed else "**FAILED**"
        lines.append(f"- **Aggregate**: `{aggregate:.2f}` ({verdict})")
    else:
        lines.append("- **Aggregate**: *(not available)*")
    if failure_mode:
        lines.append(f"- **Failure mode**: `{failure_mode}`")
    if scores:
        lines.append("- **Axis scores** (0–100):")
        all_axes = list(_KEYPOINT_AXES) + [ax for ax, _ in _JUDGE_AXES]
        idx = 0
        for ax in all_axes:
            blk = scores.get(ax)
            if not blk:
                continue
            idx += 1
            val = blk.get("value")
            status = blk.get("status") or "scored"
            disp = f"{val:.1f}" if isinstance(val, (int, float)) else "—"
            lines.append(f"  {idx}. `{ax}` → **{disp}** *(status: {status})*")

    if mode == "none":
        return "\n".join(lines).rstrip()

    # 3. Per-keypoint (GT-based) section
    acc_blk = scores.get("keypoint_accuracy") or {}
    acc_detail = acc_blk.get("detail") or {}
    acc_per_kp = acc_detail.get("per_kp") or []
    cov_detail = (scores.get("keypoint_coverage") or {}).get("detail") or {}
    cov_by_id  = {r["id"]: r for r in (cov_detail.get("per_kp") or [])}

    if acc_per_kp:
        lines.append("")
        lines.append("## 🎯 Per-keypoint feedback (ground-truth based)")
        lines.append("")
        for i, kp in enumerate(acc_per_kp, 1):
            kid       = kp.get("id", f"kp_{i}")
            qt        = kp.get("question_tag") or ""
            agent_val = kp.get("agent_value")
            gt_val    = kp.get("gt_value")
            score     = float(kp.get("score") or 0.0)
            mark = "✅" if score >= 0.99 else ("⚠️" if score > 0 else "❌")
            cov = cov_by_id.get(kid, {}).get("coverage")
            cov_note = (f", coverage `{cov:.2f}`"
                        if isinstance(cov, (int, float)) else "")
            tag_note = f" *[{qt}]*" if qt else ""
            has_gt = (agent_val is not None) or (gt_val is not None)
            lines.append(
                f"{i}. {mark} **{kid}**{tag_note} — accuracy `{score:.2f}`"
                f"{cov_note}"
            )
            if has_gt:
                lines.append(f"   - your answer: `{_fmt_value(agent_val)}`")
                if score < 0.99:
                    lines.append(f"   - **correct**: `{_fmt_value(gt_val)}`")
            else:
                lines.append("   - *(report-only keypoint — no structured-answer field; "
                             "judged from your report text)*")

    # 4. Judge-evaluated dimensions section
    judge_present = any(scores.get(ax) for ax, _ in _JUDGE_AXES)
    if judge_present:
        lines.append("")
        lines.append("## 🧑‍⚖️ Judge-evaluated report dimensions")
        lines.append("")
        for i, (ax, label) in enumerate(_JUDGE_AXES, 1):
            blk = scores.get(ax)
            if not blk:
                continue
            val = blk.get("value")
            status = blk.get("status") or "scored"
            disp = f"{val:.1f}/100" if isinstance(val, (int, float)) else "—"
            lines.append(f"{i}. **{label}** (`{ax}`) → **{disp}** "
                         f"*(status: {status})*")
            detail = blk.get("detail") or {}
            if ax == "report_faithfulness":
                _emit_faithfulness_detail(lines, detail, mode)
            elif ax == "report_quality":
                _emit_quality_detail(lines, detail, mode)

    return "\n".join(lines).rstrip()


def _emit_faithfulness_detail(lines: list[str], detail: dict,
                              mode: FeedbackMode) -> None:
    reason = detail.get("reason")
    if reason:
        lines.append(f"   - Skipped: `{reason}`")
        return
    tally = detail.get("tier_distribution") or {}
    if tally:
        parts = [f"{k}={v}" for k, v in tally.items() if v]
        if parts:
            lines.append("   - Atomic-fact tally: " + ", ".join(parts))
    if mode != "detailed":
        return
    flagged = [f for f in (detail.get("atomic_facts") or [])
               if f.get("verdict") in {"speculation", "contradicts_keypoint",
                                       "tier3_general_knowledge"}]
    if flagged:
        lines.append("   - Flagged statements in your report:")
        for f in flagged[:6]:
            lines.append(
                f"     - *{f.get('verdict')}*: {(f.get('fact') or '')[:200]}"
            )


def _emit_quality_detail(lines: list[str], detail: dict,
                         mode: FeedbackMode) -> None:
    hits     = detail.get("required_hits") or []
    partial  = detail.get("required_partial") or []
    misses   = detail.get("required_misses") or []
    violations = detail.get("forbidden_violations") or []
    rationale  = detail.get("rationale") or ""
    if hits or partial or misses:
        lines.append(
            f"   - Required signals: hit={len(hits)}, partial={len(partial)}, "
            f"missed={len(misses)}"
        )
    if misses:
        lines.append("   - Missing signals: " +
                     ", ".join(f"`{s}`" for s in misses))
    if violations:
        lines.append("   - Forbidden-signal violations: " +
                     ", ".join(f"`{v}`" for v in violations))
    if rationale and mode == "detailed":
        snippet = rationale.strip().replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400] + "…"
        lines.append(f"   - Judge rationale: {snippet}")


def render_episode_history(history: list[EpisodeTurn]) -> str:
    if not history:
        return ""
    parts = ["[Episode history — your past evaluations]\n"]
    for turn in reversed(history):
        parts.append(turn.rendered)
        parts.append("")
    return "\n".join(parts).strip()
