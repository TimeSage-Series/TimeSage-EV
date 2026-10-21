"""Agent ↔ Environment contract.

The environment runs agents as subprocesses. cwd is set to the sandbox
/root by the environment. Restricted env vars are injected. Everything
else (LM, tool implementations, planning strategy) is the agent's
internal business.

Two wire modes:

  * **Single-period** (`evsandbox run`): one JSON `AgentRequest` line on
    stdin, one JSON `AgentResponse` line on stdout, process exits.
    Schema below.

  * **Episode interactive** (`evsandbox episode`): multi-message
    stdin/stdout loop. The agent subprocess stays alive across all
    periods so conversation memory accumulates naturally.

        parent → child  : SETUP — one JSON line
          {"scenario_dir": ..., "agent_args": ...,
           "episode": {"interactive": true,
                       "episode_dir": "<abs path>",
                       "periods": ["p1", "p2", ...]}}

        REPEAT for each period:
          parent → child : {"period": "<p>", "cutoff": "<p>", "prompt": "<text>"}
          child  → parent: {"period": "<p>", "status": "ok"|"incomplete"|"agent_crash",
                            "structured_answer": {...}, "report": "<md>",
                            "wall_ms": <int>, "error": "..."?,
                            "usage": {"input_tokens": <int>,
                                      "output_tokens": <int>}?}

        parent → child  : {"done": true}
        child  → parent : {"status": "ok", "mode": "episode",
                           "periods": [...], "wall_ms": <int>}

    Env vars are fixed when the parent spawns the child, so ENV_CUTOFF
    starts at the FIRST period's cutoff; each period message carries that
    period's `cutoff`, and the child must apply it (`apply_period_cutoff`)
    before doing any work for the period.

    Each period has its own `timeout_s` budget, counted from when the
    parent sends the period message.

    Before sending a period message the parent refreshes the child's cwd
    to that period; the child never rebuilds the sandbox itself.

    Between periods, the parent scores the just-received submission and
    prepends a markdown feedback block (see `evsandbox.feedback`) to the
    NEXT period's prompt. The child has no scoring responsibilities —
    it just runs the agent for the prompt it gets.

This file is the SOURCE OF TRUTH for the single-period schema below;
agents/README.md references it. The interactive loop's schema lives
in this docstring (no dataclass — it's just a couple of fields).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Env vars the environment sets for the agent subprocess.
# Agents may read these directly; the environment guarantees their presence
# in the listed cases.
# ---------------------------------------------------------------------------

ENV_CUTOFF      = "TIMESAGE_CUTOFF"          # period string, e.g. "2024-05"
ENV_AUDIT_PATH  = "TIMESAGE_AUDIT_PATH"      # set iff network audit is enabled
ENV_SEARXNG     = "TIMESAGE_SEARXNG"         # set iff IATA scenario uses web search
ENV_RUN_ID      = "TIMESAGE_RUN_ID"          # opaque id for trace correlation
ENV_TRACE_PATH  = "TIMESAGE_TRACE_PATH"      # streaming target — agents append trace rows
                                             # as JSONL so partial traces survive timeout/crash


def apply_period_cutoff(msg: dict) -> str:
    """Episode mode: set ENV_CUTOFF from a period message and return it.

    Uses the message's `cutoff`, falling back to its `period` for parents
    that predate the field.
    """
    cutoff = msg.get("cutoff") or msg["period"]
    os.environ[ENV_CUTOFF] = cutoff
    return cutoff


# ---------------------------------------------------------------------------
# Wire schemas
# ---------------------------------------------------------------------------

@dataclass
class EpisodeTurn:
    """One past period's evaluation, fed back to the agent on the next turn.

    Built only in `episode` mode, after the period is scored; its `rendered`
    markdown is prepended to the next period's prompt.
    """
    period: str                                # the past period this turn refers to
    aggregate: float                           # score record aggregate
    passed: bool
    axis_scores: dict[str, float] = field(default_factory=dict)
    structured_answer: dict[str, Any] = field(default_factory=dict)
                                                # the agent's own past answer (echo)
    # Mode-dependent detail. Always present but content depends on
    # feedback_mode used by the runner:
    #   "none":     keypoint_results = []      (no per-kp breakdown)
    #   "score":    keypoint_results = [{"id":..., "passed": True/False}, ...]
    #   "detailed": keypoint_results = [{"id":..., "passed": ..., "agent_value":...,
    #                                    "correct_value": ...}], plus
    #               faithfulness_notes = [...]
    keypoint_results:   list[dict[str, Any]] = field(default_factory=list)
    faithfulness_notes: list[str] = field(default_factory=list)
    # A pre-rendered human-readable summary that the agent may include
    # verbatim in its next-turn prompt without re-formatting.
    rendered: str = ""


@dataclass
class AgentRequest:
    """One JSON line on the agent's stdin."""
    scenario_dir: str                        # absolute path to the scenario root
    period:       str                        # the report period being briefed on
    prompt:       str                        # the rephrased user-facing prompt
    agent_args:   dict[str, Any] = field(default_factory=dict)
                                              # agent-specific (lm_model, seed, ...)


@dataclass
class AgentResponse:
    """One JSON line on the agent's stdout. Last line wins if multiple."""
    status:            str                   # "ok" | "incomplete" | "agent_crash"
    structured_answer: dict[str, Any] = field(default_factory=dict)
    report:            str = ""
    trace:             list[dict[str, Any]] = field(default_factory=list)
    wall_ms:           int = 0
    error:             Optional[str] = None  # populated iff status != "ok"


# ---------------------------------------------------------------------------
# Status sentinels (string constants so the protocol is JSON-native)
# ---------------------------------------------------------------------------

STATUS_OK          = "ok"
STATUS_INCOMPLETE  = "incomplete"          # ran but did not emit both answer + report
STATUS_AGENT_CRASH = "agent_crash"         # exception inside the agent process
STATUS_TIMEOUT     = "agent_timeout"       # parent-side timeout, agent never produced
STATUS_LEAKAGE     = "leakage_detected"   # post-run audit found a violation
