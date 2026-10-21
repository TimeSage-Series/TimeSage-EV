"""Auto-induction: ask the agent's own LLM after each successful period
whether anything worth saving as a skill happened, and persist it if so.

Why this exists: agent-volition induction (the agent calling `induct_skill`
in code) works in principle but in practice small models stay focused on
the task and rarely use the tool even when explicitly prompted. Auto-
induction takes the curation decision out of the agent's hands and into
a dedicated 1-shot LLM call per period, decoupling task performance from
library-building.

The auto-inducted skill MUST satisfy the same standards as agent-inducted
ones (description ≤ 120 chars, code defines `def skill(...)`, inputs_schema
matches signature, output_type declared, etc.) — `skill_store.save_skill`
enforces these uniformly.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import skill_store


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a SKILL CURATOR for a multi-period evaluation agent. After each "
    "period, you inspect the agent's actions and decide whether to extract "
    "ONE reusable skill into the skill library — so a future period (of "
    "this scenario or a similar one) can invoke it directly instead of "
    "re-deriving the logic.\n\n"

    "A SKILL can be either of two shapes — pick whichever fits the agent's "
    "actual work:\n"
    "  (a) **Utility function** — a small helper like a CSV loader for "
    "this dataset's exact schema, a date-to-period converter, a threshold "
    "classifier, a row-lookup-by-key. Usually 5-15 LOC.\n"
    "  (b) **Wrapped workflow** — a sequence of steps the agent repeats "
    "every period (read CSV → extract latest row → compute against "
    "5-year window → classify into band, etc.), packaged as ONE function. "
    "Usually 15-40 LOC.\n\n"

    "BOTH shapes are represented as a single top-level `def skill(...)`. "
    "Workflows just have more lines inside. Both are registered as "
    "callable tools — the agent invokes them by name.\n\n"

    "DO NOT induct any of the following:\n"
    "  - the literal final answer (it's period-specific, not reusable);\n"
    "  - code that failed at runtime in the trace below;\n"
    "  - one-liners or string-formatting glue that's faster to inline than "
    "to look up by name;\n"
    "  - anything that hard-codes the current period — skills must be "
    "parameterised over the data they look up.\n\n"

    "Constraints when you DO induct (these are HARD — your output will be "
    "validated and rejected if any fail):\n"
    "  - `name`: snake_case slug, ^[a-z0-9][a-z0-9_]*$.\n"
    "  - `description`: ≤ 1 sentence, ≤ 120 CHARACTERS. State the SITUATION "
    "the skill applies to and what it RETURNS. No examples. No caveats — "
    "those go in `notes`.\n"
    "  - `code`: Python source defining exactly one top-level "
    "`def skill(...)`. **Imports must be INSIDE the function body** "
    "(sandbox-safe re-import on each call).\n"
    "  - `inputs_schema`: dict mapping each `skill()` parameter name to "
    "`{type, description, nullable?}`. Keys MUST be valid Python "
    "identifiers and match the function signature exactly. Allowed "
    "types: 'string', 'integer', 'number', 'boolean', 'object', 'array'.\n"
    "  - `output_type`: one of 'string', 'integer', 'number', 'boolean', "
    "'object', 'array'.\n"
    "  - `notes`: optional human-readable caveats / assumptions; no "
    "length cap.\n\n"

    "Output policy — return ONE of:\n"
    "  • the literal JSON token `null` (lowercase, no quotes) if nothing "
    "in this period crosses the bar;\n"
    "  • a single JSON object with the fields above, and NOTHING ELSE.\n\n"

    "Do NOT wrap the JSON in code fences. Do NOT add commentary before or "
    "after the JSON. The parser is strict."
)


def _build_user_message(
    *,
    period: str,
    scenario_id: str,
    tier: str,
    score: Optional[float],
    final_answer: Any,
    action_steps: list[dict],
    existing_skills: list[tuple[str, str]],
) -> str:
    """Render the trace excerpt + period context block."""
    parts = [
        f"## Period\n{period}",
        f"## Scenario\n{scenario_id}  (tier={tier})",
    ]
    if score is not None:
        parts.append(f"## Score on this period\n{score}")

    fa = final_answer
    if isinstance(fa, dict):
        fa = json.dumps(fa, ensure_ascii=False)
    parts.append(f"## Final answer the agent submitted\n{str(fa)[:600]}")

    # Send the full (name, description) table so the curator can do
    # semantic dedup, not just name-collision avoidance.
    if existing_skills:
        lib_lines = ["## Existing skills in the library (DO NOT DUPLICATE)",
                     "",
                     "If your candidate skill is semantically the same as ANY entry "
                     "below — even with different name or slightly different code — "
                     "you MUST return `null` instead of saving a near-copy. The "
                     "library is meant to be small and orthogonal.",
                     ""]
        for nm, desc in existing_skills:
            lib_lines.append(f"- **{nm}** — {desc}")
        parts.append("\n".join(lib_lines))
    else:
        parts.append("## Existing skills in the library\n"
                     "(library is empty — feel free to seed it)")

    parts.append("## Agent actions this period (oldest → newest)")
    if not action_steps:
        parts.append("(no action steps captured)")
    else:
        for s in action_steps:
            step_no = s.get("step_number")
            code = (s.get("code_action") or "").strip()
            obs = (s.get("observations") or "").strip()
            err = s.get("error")
            parts.append(f"### Step {step_no}")
            if code:
                parts.append("```python\n" + code[:1800] + "\n```")
            if obs:
                parts.append(f"Observation:\n```\n{obs[:600]}\n```")
            if err:
                parts.append(f"⚠️ Error in this step: {str(err)[:200]}")
    parts.append("")
    parts.append("Now produce your output: either `null` or a single JSON "
                 "object as specified.")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Trace digestion
# ---------------------------------------------------------------------------

def _read_period_actions(trace_path: Path, period: str) -> list[dict]:
    """Extract action-kind entries for the given period from trace.jsonl.

    Periods are demarcated by `period_start` / `period_done` rows. We collect
    every `kind == "action"` row between the LAST period_start with that
    period name and the next period_done.
    """
    if not trace_path.exists():
        return []
    actions: list[dict] = []
    in_period = False
    with trace_path.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            kind = r.get("kind")
            if kind == "period_start" and r.get("period") == period:
                in_period = True
                actions = []   # reset in case there's an earlier (failed) start
                continue
            if not in_period:
                continue
            if kind == "period_done":
                in_period = False
                break
            if kind == "action":
                actions.append(r)
    return actions


# ---------------------------------------------------------------------------
# LLM call + parsing
# ---------------------------------------------------------------------------

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Optional[dict]:
    """Try to parse the model's reply as a skill JSON object.

    Accepts:
      • the literal token `null` (returns None, no skill to induct)
      • a single top-level JSON object (returns dict)
      • a JSON object wrapped in ```json``` fences (strip + retry)
    """
    text = (text or "").strip()
    if text.lower() == "null":
        return None
    # Strip optional code fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        m = _JSON_OBJECT_RE.search(text)
        if not m:
            return None
        try:
            v = json.loads(m.group(0))
            return v if isinstance(v, dict) else None
        except json.JSONDecodeError:
            return None


def _model_generate(model: Any, system_prompt: str, user_msg: str) -> str:
    """Call the model.generate(messages=[...]) API used by smolagents."""
    from smolagents.models import ChatMessage, MessageRole              # noqa: WPS433
    msgs = [
        ChatMessage(role=MessageRole.SYSTEM,
                    content=[{"type": "text", "text": system_prompt}]),
        ChatMessage(role=MessageRole.USER,
                    content=[{"type": "text", "text": user_msg}]),
    ]
    resp = model.generate(messages=msgs, stop_sequences=None)
    c = resp.content
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(part.get("text", "") if isinstance(part, dict) else str(part)
                         for part in c)
    return str(c)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def auto_induct_period(
    *,
    model: Any,
    trace_path: Path,
    skill_dir: Path,
    period: str,
    scenario_id: str,
    tier: str,
    llm_slug: str,
    score: Optional[float],
    final_answer: Any,
    min_score: float = 80.0,
    only_if_ok: bool = True,
    period_status: str = "ok",
) -> dict:
    """Run one auto-induction pass after a period completes.

    Returns a dict with keys: `triggered`, `decision`, `saved_name`, `error`,
    `model_reply_chars`. Never raises — failure is reported via the dict
    so the worker can log + continue.
    """
    out: dict = {
        "triggered": False, "decision": "skipped",
        "saved_name": None, "error": None, "model_reply_chars": 0,
    }
    if only_if_ok and period_status != "ok":
        out["decision"] = "skipped:not_ok"
        return out
    if score is not None and float(score) < min_score:
        out["decision"] = f"skipped:score_below_{min_score}"
        return out

    actions = _read_period_actions(Path(trace_path), period)
    if not actions:
        out["decision"] = "skipped:no_actions"
        return out

    existing = skill_store.list_skills(skill_dir)   # [(name, description), ...]
    user_msg = _build_user_message(
        period=period, scenario_id=scenario_id, tier=tier,
        score=score, final_answer=final_answer,
        action_steps=actions, existing_skills=existing,
    )

    out["triggered"] = True
    try:
        reply = _model_generate(model, _SYSTEM_PROMPT, user_msg)
    except Exception as exc:                                          # noqa: BLE001
        out["error"] = f"llm_call_failed: {type(exc).__name__}: {exc}"
        out["decision"] = "skipped:llm_error"
        return out
    out["model_reply_chars"] = len(reply or "")

    obj = _extract_json(reply)
    if obj is None:
        out["decision"] = "model_returned_null"
        return out

    required = {"name", "description", "code", "inputs_schema", "output_type"}
    missing = required - set(obj.keys())
    if missing:
        out["decision"] = "model_returned_invalid"
        out["error"] = f"missing fields: {sorted(missing)}"
        return out

    # If name collides with an existing skill, append a numeric suffix.
    base_name = obj["name"]
    name = base_name
    n = 1
    while (skill_dir / f"{name}.md").exists():
        n += 1
        name = f"{base_name}_v{n}"
    if name != base_name:
        obj["name"] = name

    try:
        md_path = skill_store.save_skill(
            skill_dir,
            name=obj["name"],
            description=obj["description"],
            code=obj["code"],
            inputs_schema=obj["inputs_schema"],
            output_type=obj["output_type"],
            notes=obj.get("notes") or "",
            tags=obj.get("tags") or [],
            inducted_from={
                "auto":      True,
                "scenario":  scenario_id,
                "period":    period,
                "llm_slug":  llm_slug,
                "score":     score,
                "ts":        datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:                                          # noqa: BLE001
        out["error"] = f"save_skill_rejected: {type(exc).__name__}: {exc}"
        out["decision"] = "save_rejected"
        return out

    out["decision"] = "saved"
    out["saved_name"] = obj["name"]
    out["saved_path"] = str(md_path)
    return out
