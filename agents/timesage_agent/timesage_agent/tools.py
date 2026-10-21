"""Two skill-aware tools that augment the smolagents agent.

* ``induct_skill`` — agent-triggered save: writes a (<name>.md, <name>.py)
  pair into the configured skill_dir. After the current period completes,
  the worker re-scans the dir and registers the new skill as a callable
  tool for subsequent periods.

* ``retrieve_skill`` — agent-triggered read: returns the markdown body
  (notes + code) of a saved skill so the agent can decide whether to
  invoke it. Direct invocation is also available — the skill itself
  is registered as a tool under its declared name.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from smolagents import Tool

from . import skill_store


class InductSkillTool(Tool):
    """Save a reusable Python function to the per-sweep skill library."""

    name = "induct_skill"
    description = (
        "Save a reusable Python function to the skill library. After this "
        "call, the function becomes a callable tool in subsequent periods "
        "of this sweep — future agent runs (including YOU on the next "
        "period) invoke it by name without paying the cost of re-writing "
        "and re-debugging the same code.\n\n"
        "**WHEN to call this**: any time you write a small idiom that would "
        "clearly apply to OTHER periods or scenarios — e.g., loading the "
        "scenario's CSV with the right column names, parsing a date column "
        "into a period label, classifying a value into bands, looking up a "
        "row by week, etc. Call BEFORE `final_answer` so the save happens "
        "while the relevant context is fresh.\n\n"
        "**WHAT makes a good skill**: a small (≤30 line) function that does "
        "one thing and returns a clean Python value. Bad candidates: the "
        "literal final answer dict, one-off math that won't recur.\n\n"
        "STRICT RULES on `description`: ≤ 1 sentence, ≤ 120 chars. State the "
        "situation the skill applies to and what it returns. NO examples, NO "
        "caveats — those go in `notes`. Future agents scan many descriptions "
        "at once, so brevity is essential.\n\n"
        "The skill `code` MUST define a single top-level function named "
        "exactly `skill(...)` whose signature matches `inputs_schema`."
    )
    inputs = {
        "name": {
            "type": "string",
            "description": "snake_case slug, unique within sweep (^[a-z0-9][a-z0-9_]*$).",
        },
        "description": {
            "type": "string",
            "description": "≤ 1 sentence, ≤ 120 chars. The situation it applies to + what it returns.",
        },
        "code": {
            "type": "string",
            "description": "Python source code that defines a top-level `def skill(...)` function. "
                           "Imports must be inside the function body (sandbox-safe). "
                           "Do NOT wrap with <code>...</code> tags.",
        },
        "inputs_schema": {
            "type": "object",
            "description": "JSON schema dict for the function args, smolagents Tool.inputs shape. "
                           "Example: {\"iso_week\": {\"type\": \"string\", \"description\": \"...\"}}.",
        },
        "output_type": {
            "type": "string",
            "description": "smolagents output type: one of 'string', 'object', 'integer', 'number', 'boolean', 'array'.",
        },
        "notes": {
            "type": "string",
            "description": "Optional human-readable docs / caveats. No strict length cap here.",
            "nullable": True,
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional keywords for human navigation (e.g., ['pandas', 'csv', 'iso_week']).",
            "nullable": True,
        },
    }
    output_type = "object"

    def __init__(self, skill_dir: Path,
                 *,
                 scenario_id: str = "",
                 period: str = "",
                 llm_slug: str = ""):
        super().__init__()
        self._skill_dir = Path(skill_dir)
        self._scenario_id = scenario_id
        self._period = period
        self._llm_slug = llm_slug
        # Track which skills were saved this period — the worker reads this
        # after agent.run() to decide whether to re-scan skill_dir for new
        # tools before the next period.
        self.saved_this_period: list[str] = []

    def update_context(self, *, scenario_id: str = "",
                       period: str = "", llm_slug: str = "") -> None:
        """Refresh the inducted_from fields between periods. Called by the worker."""
        if scenario_id: self._scenario_id = scenario_id
        if period:      self._period = period
        if llm_slug:    self._llm_slug = llm_slug
        self.saved_this_period = []

    def forward(self,
                name: str,
                description: str,
                code: str,
                inputs_schema: Any,
                output_type: str,
                notes: Optional[str] = None,
                tags: Optional[list] = None) -> dict:
        # Some models pass JSON strings instead of dicts/lists; be lenient.
        if isinstance(inputs_schema, str):
            try:
                inputs_schema = json.loads(inputs_schema)
            except Exception:
                pass
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = [tags]

        inducted_from = {
            "scenario": self._scenario_id,
            "period":   self._period,
            "llm_slug": self._llm_slug,
            "ts":       datetime.now(timezone.utc).isoformat(),
        }
        try:
            md_path = skill_store.save_skill(
                self._skill_dir,
                name=name,
                description=description,
                code=code,
                inputs_schema=inputs_schema if isinstance(inputs_schema, dict) else {},
                output_type=output_type,
                notes=notes or "",
                tags=list(tags or []),
                inducted_from=inducted_from,
            )
        except Exception as exc:
            return {
                "saved": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        self.saved_this_period.append(name)
        return {
            "saved": True,
            "name":  name,
            "path":  str(md_path),
            "note":  ("Skill will be callable as a tool starting NEXT period. "
                      "For the rest of THIS period, write the code inline if you need it again."),
        }


class RetrieveSkillTool(Tool):
    """Read a skill's full markdown body (notes + code) by name."""

    name = "retrieve_skill"
    description = (
        "Read a skill's full documentation (notes + code) by name. Available "
        "skill names + descriptions are listed in the system prompt under "
        "'Available skills'. Use this when you want to see exactly how a skill "
        "is implemented (or read its notes) BEFORE deciding to invoke it.\n\n"
        "Note: you can also invoke any listed skill directly by its name — "
        "no need to retrieve first if the description tells you enough."
    )
    inputs = {
        "name": {
            "type": "string",
            "description": "Exact skill name from the 'Available skills' index.",
        },
    }
    output_type = "string"

    def __init__(self, skill_dir: Path):
        super().__init__()
        self._skill_dir = Path(skill_dir)

    def forward(self, name: str) -> str:
        try:
            return skill_store.load_skill_markdown(self._skill_dir, name)
        except FileNotFoundError:
            avail = ", ".join(n for n, _ in skill_store.list_skills(self._skill_dir))
            return (
                f"Skill {name!r} not found in the library. "
                f"Available skills: {avail or '(none)'}."
            )
