"""Experiment config files for the evsandbox CLI (`--config exp.yaml`).

A config pins what decides a result — the agent and its model, the judge,
the isolation — so a run can be repeated and compared. Command-line flags
override it; the CLI's own defaults fill whatever neither sets. Secrets and
endpoints stay in the environment (.env.example).

    target: sonnet-easy-v1
    agent:
      name: smolagents_agent            # or  cmd: "python -m my_agent.worker"
      args: {lm_provider: anthropic, lm_model: claude-sonnet-4-6, max_steps: 12}
    judge:
      backend: anthropic                # mock | anthropic | claude_thinking |
      model: claude-haiku-4-5-20251001  #   claude_cli | openrouter | spike
      quality_model: claude-sonnet-4-6
      thinking: middle
      max_tokens: 2048                  # judge reply budget
      extra_body: {}                    # spike / openrouter request extras, e.g.
                                        #   {chat_template_kwargs: {thinking: false}}
      by_kind:                          # per call kind (coverage | decompose |
        verify:                         #   verify | quality): replaces the above
          extra_body: {reasoning_effort: low}
          max_tokens: 4096
    isolation: bwrap
    timeout: 300                        # per task / per episode period
    # used by the commands that take them, ignored by the rest:
    tier: easy
    mode: independent                   # sweep: independent | episode
    strategies: [pass_through, persona] # sweep; run/episode take `strategy`
    feedback_mode: score
    seed: 0
    concurrency: 32
    rpm_cap: 600
    max_tasks: 0
    periods: [2024-05, 2024-06]         # episode
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

#: Top-level keys, by the CLI option (argparse dest) each one sets.
TOP_LEVEL = {
    "target": "target", "isolation": "isolation", "timeout": "timeout",
    "tier": "tier", "mode": "mode", "strategy": "strategy",
    "strategies": "strategies", "feedback_mode": "feedback_mode",
    "seed": "seed", "concurrency": "concurrency", "rpm_cap": "rpm_cap",
    "max_tasks": "max_tasks", "periods": "periods",
}
AGENT_KEYS = {"name": "agent", "cmd": "agent_cmd"}          # plus `args`
JUDGE_KEYS = {"backend": "judge", "model": "judge_model",
              "quality_model": "judge_quality_model", "thinking": "judge_thinking",
              "max_tokens": "judge_max_tokens", "extra_body": "judge_extra_body",
              "by_kind": "judge_by_kind"}

#: Values argparse would check with `choices`; config values bypass that.
CHOICES = {
    "isolation": ("none", "bwrap"),
    "mode": ("independent", "episode"),
    "strategy": ("pass_through", "persona"),
    "feedback_mode": ("none", "score", "detailed"),
    "judge": ("mock", "anthropic", "claude_thinking", "claude_cli", "openrouter", "spike"),
    "judge_thinking": ("low", "middle", "high"),
}


def load_config(path: str | Path) -> dict[str, Any]:
    """Read a config file into {argparse dest: value}, plus "agent_args".

    Unknown keys are an error, so a typo cannot silently fall back to a
    default.
    """
    doc = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(doc, dict):
        raise SystemExit(f"{path}: expected a mapping at the top level")
    out: dict[str, Any] = {}

    def section(name: str, keys: dict[str, str], extra: tuple[str, ...] = ()) -> dict:
        sec = doc.pop(name, None) or {}
        if not isinstance(sec, dict):
            raise SystemExit(f"{path}: `{name}` must be a mapping")
        bad = sorted(set(sec) - set(keys) - set(extra))
        if bad:
            raise SystemExit(f"{path}: unknown key(s) in `{name}`: {bad}; "
                             f"allowed: {sorted([*keys, *extra])}")
        out.update({keys[k]: v for k, v in sec.items() if k in keys})
        return sec

    agent = section("agent", AGENT_KEYS, extra=("args",))
    if agent.get("args") is not None:
        if not isinstance(agent["args"], dict):
            raise SystemExit(f"{path}: `agent.args` must be a mapping")
        out["agent_args"] = dict(agent["args"])
    section("judge", JUDGE_KEYS)

    bad = sorted(set(doc) - set(TOP_LEVEL))
    if bad:
        raise SystemExit(f"{path}: unknown key(s): {bad}; "
                         f"allowed: {sorted([*TOP_LEVEL, 'agent', 'judge'])}")
    out.update({TOP_LEVEL[k]: v for k, v in doc.items()})

    if "judge_extra_body" in out and not isinstance(out["judge_extra_body"], dict):
        raise SystemExit(f"{path}: `judge.extra_body` must be a mapping")
    by_kind = out.get("judge_by_kind")
    if by_kind is not None:
        from evbench.evaluator.judge import JUDGE_KINDS, KIND_OPTIONS
        if not isinstance(by_kind, dict) or not all(isinstance(v, dict) for v in by_kind.values()):
            raise SystemExit(f"{path}: `judge.by_kind` must map a call kind to a mapping")
        bad = sorted(set(by_kind) - set(JUDGE_KINDS)) + \
            sorted({o for v in by_kind.values() for o in v} - set(KIND_OPTIONS))
        if bad:
            raise SystemExit(f"{path}: unknown key(s) in `judge.by_kind`: {bad}; "
                             f"kinds {list(JUDGE_KINDS)}, options {list(KIND_OPTIONS)}")
    for key in ("strategies", "periods"):          # lists → the CLI's comma form
        if isinstance(out.get(key), list):
            out[key] = ",".join(str(x) for x in out[key])
    for dest, allowed in CHOICES.items():
        if dest in out and out[dest] not in allowed:
            raise SystemExit(f"{path}: {dest}={out[dest]!r} is not one of {allowed}")
    return out
