"""TimeSage-specific smolagents tools.

* TimeSageFinalAnswer — replaces smolagents' default FinalAnswerTool.
  Forces the agent to produce BOTH a structured `answer` (dict matching
  answer_schema.json) AND a markdown `report`. We need both to satisfy
  the evsandbox response contract.

* TimeSageWebSearch — wraps evsandbox.network.search_with_isolation so the
  agent gets time-isolated, audited web access. Cutoff and audit_path
  come from the env / runner.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from smolagents import Tool


class TimeSageFinalAnswer(Tool):
    """Terminal tool: captures structured answer + report and stops the agent."""

    name = "final_answer"
    description = (
        "Submit your final answer. Call this exactly once when you are "
        "done analyzing. Pass two arguments:\n"
        "  * answer (dict): JSON object matching the required keys of "
        "answer_schema.json.\n"
        "  * report (str):  markdown narrative explaining your findings. "
        "Cite only CSV cells from timeseries.csv or prior-period "
        "files under gt_source/. Never cite the current period's "
        "report."
    )
    inputs = {
        "answer": {
            "type": "object",
            "description": "Structured answer matching answer_schema.json.",
        },
        "report": {
            "type": "string",
            "description": "Markdown narrative report.",
        },
    }
    output_type = "object"

    def __init__(self):
        super().__init__()
        self.captured: dict[str, Any] = {"answer": None, "report": None}

    def forward(self, answer: Any, report: str) -> dict:
        # Some models will pass a JSON-string instead of a dict. Be lenient.
        if isinstance(answer, str):
            try:
                answer = json.loads(answer)
            except Exception:                                       # noqa: BLE001
                pass
        self.captured["answer"] = answer
        self.captured["report"] = report
        return {"ok": True}


class CompactMemoryTool(Tool):
    """Agent-controlled memory compaction request.

    The agent calls this tool to schedule a memory compaction for AFTER
    the current period finishes. The framework reads `self.requested`
    at the period boundary; if True, runs `agent.compact_memory(...)`
    and resets the flag.

    This is the smolagents-idiomatic way to expose the capability —
    the agent's decision shows up as a regular `tool_call` step in
    the trace, no string-matching on the report needed.
    """

    name = "request_memory_compaction"
    description = (
        "Schedule a memory compaction AFTER the current period finishes. "
        "Use this if your conversation memory is filling with material "
        "you no longer need (failed code attempts, long observations, "
        "patterns you've already learned). The framework will summarize "
        "what you've learned across past periods, reset memory to that "
        "summary, and continue with the next period. Typical cadence: "
        "once every ~5 periods. Has no immediate effect — does NOT abort "
        "the current period."
    )
    inputs = {
        "reason": {
            "type": "string",
            "description": "One-line justification (e.g. 'memory full of "
                           "retried code from CSV exploration; pattern now "
                           "stable, no longer need full history').",
            "nullable": True,
        },
    }
    output_type = "object"

    def __init__(self):
        super().__init__()
        self.requested = False
        self.last_reason: Optional[str] = None

    def forward(self, reason: Optional[str] = None) -> dict:
        self.requested = True
        self.last_reason = reason or ""
        return {
            "scheduled": True,
            "applies_after": "current period",
            "reason_recorded": self.last_reason,
            "note": "Compaction will run BETWEEN periods, not now. Continue "
                    "with final_answer for THIS period as usual.",
        }

    def reset(self) -> None:
        """Called by the worker after compaction completes."""
        self.requested = False
        self.last_reason = None


class TimeSageWebSearch(Tool):
    """Time-isolated web search via evsandbox.network.search_with_isolation.

    Only available when the scenario opts into web search (the worker
    decides whether to add this tool). Cutoff and audit_path are captured
    at construction time.
    """

    name = "web_search"
    description = (
        "Search the web for context. Results are restricted to pages "
        "archived BEFORE the analysis cutoff (no future leakage). Returns "
        "a list of dicts, each {url, archived_at, html_snippet, source}. "
        "Use this instead of `requests`/`urllib`, which are not available "
        "in the sandbox."
    )
    inputs = {
        "query": {
            "type": "string",
            "description": "Free-text search query.",
        },
        "n": {
            "type": "integer",
            "description": "Max number of results to return (1–10).",
            "nullable": True,
        },
    }
    output_type = "array"

    def __init__(self, cutoff: str, audit_path: Optional[Path] = None):
        super().__init__()
        self._cutoff = cutoff
        self._audit_path = audit_path

    def forward(self, query: str, n: int = 5) -> list[dict]:
        from evsandbox.network import search_with_isolation             # noqa: WPS433
        n = max(1, min(int(n or 5), 10))
        return search_with_isolation(
            query=query, n=n, cutoff=self._cutoff,
            audit_path=self._audit_path,
        )
