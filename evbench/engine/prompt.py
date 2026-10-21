"""Build the prompt an agent is given for one (scenario, period).

A prompt has four sections:

    # Task, # Input     session_brief.md
    # Question          question_template.md rendered for the period, then
                        rephrased: each question with its options and the
                        rule that decides them
    # Answer Format     generated from answer_schema.json: which field
                        answers which question

Rephrasing paraphrases the canonical question into a natural user prompt
without altering its keypoint identity set.

v2: only `pass_through` and `persona`. The `distractor` strategy was removed
because it tested robustness to an artificial noise distribution rather
than the agent's analytical capability.

"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .question import render_question
from .tasks import read_session_brief


Strategy = Literal["pass_through", "persona"]
ALL_STRATEGIES: tuple[Strategy, ...] = ("pass_through", "persona")


@dataclass
class RephrasedPrompt:
    text: str
    strategy: Strategy
    keypoint_count_preserved: bool


def _count_numbered(s: str) -> int:
    return len(re.findall(r"(?m)^\s*\d+\.\s", s))


def _persona(question_md: str, domain: str) -> str:
    return (
        f"As a senior {domain.replace('_', ' ')} analyst, brief me on this period.\n\n"
        + question_md
    )


def _extract_keypoint_tokens(description: str) -> list[str]:
    """Cheap nouns + numerics: lowercase alpha-num tokens of length >=3, after
    stripping common stopwords."""
    stop = {"the", "and", "for", "with", "this", "from", "over", "into", "than",
            "that", "report", "value", "must", "each", "weight", "field", "kp",
            "data", "current", "period", "given", "row", "rows", "csv", "any",
            "one", "many", "more", "less", "have", "has", "use", "using",
            "tier", "tag", "vs", "via", "per", "based"}
    toks = re.findall(r"[a-z0-9_]+", description.lower())
    return [t for t in toks if len(t) >= 3 and t not in stop]


def rephrase(question_md: str,
             scenario,
             strategy: str = "pass_through",
             seed: int = 0) -> RephrasedPrompt:
    if strategy == "pass_through":
        text = question_md
    elif strategy == "persona":
        text = _persona(question_md, scenario.domain)
    else:
        raise ValueError(
            f"unknown strategy: {strategy!r}; allowed: {ALL_STRATEGIES}"
        )
    ok = validate_keypoint_preservation(question_md, text, scenario)
    if not ok and strategy != "pass_through":
        return RephrasedPrompt(text=question_md, strategy="pass_through",
                               keypoint_count_preserved=True)
    return RephrasedPrompt(text=text, strategy=strategy,  # type: ignore[arg-type]
                           keypoint_count_preserved=ok)


def validate_keypoint_preservation(original: str, rephrased: str,
                                    scenario) -> bool:
    if _count_numbered(original) != _count_numbered(rephrased):
        return False
    rl = rephrased.lower()
    for kp in scenario.keypoints:
        toks = _extract_keypoint_tokens(kp.description)
        if not toks:
            continue
        if not any(t in rl for t in toks):
            return False
    return True


def answer_format(answer_schema: dict) -> str:
    """The # Answer Format section: the answer's fields, the i-th answering Qi.

    Options and rules are given with each question, so they are not
    repeated here.
    """
    fields = list((answer_schema.get("properties") or {}))
    lines = [f"- `{f}` — Q{i}" for i, f in enumerate(fields, 1)]
    return ("# Answer Format\n\n"
            "Every answer must conform to `answer_schema.json` in your working\n"
            "directory: a JSON object with one field per question.\n\n"
            + "\n".join(lines) + "\n")


def task_prompt(scenario, scenario_dir: Path, period: str, *,
                strategy: str = "pass_through",
                seed: int = 0) -> tuple[str, RephrasedPrompt]:
    """Full prompt for a standalone (scenario, period) run."""
    rephrased = rephrase(render_question(scenario_dir, period), scenario,
                         strategy=strategy, seed=seed)
    prompt = (read_session_brief(scenario_dir).rstrip("\n")
              + "\n\n# Question\n\n" + rephrased.text.rstrip("\n")
              + "\n\n" + answer_format(scenario.answer_schema))
    return prompt, rephrased


def episode_prompt(scenario, scenario_dir: Path, period: str, *,
                   is_first: bool, strategy: str = "pass_through",
                   seed: int = 0) -> str:
    """Construct the prompt the agent sees for one period of a continuous episode.

    First period: full session brief + rephrased question. This is the
    agent's introduction to the scenario.

    Subsequent periods: a short situational cue + the rephrased question.
    The brief and tools/sandbox rules are already in the agent's memory
    from the first turn — we only need to tell it the world has changed.
    """
    if is_first:
        return task_prompt(scenario, scenario_dir, period,
                           strategy=strategy, seed=seed)[0]
    rephrased = rephrase(render_question(scenario_dir, period), scenario,
                         strategy=strategy, seed=seed)
    return (
        f"You are now moving on to **period {period}**. Your working "
        f"directory has been refreshed:\n"
        f"  * `timeseries.csv` now extends through {period}'s release.\n"
        f"  * `gt_source/` may contain additional prior-period files "
        f"(strictly before {period}).\n"
        f"\n"
        f"Re-read whichever files you need for this period. Then answer:\n"
        f"\n"
        f"{rephrased.text}"
    )
