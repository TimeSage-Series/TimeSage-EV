"""TimeSageSmolAgent — smolagents.CodeAgent wired to TimeSage scenarios.

The agent gets:
  * a sandboxed Python interpreter (the action language; built into CodeAgent)
  * a curated import whitelist for data analysis + PDF/HTML parsing
  * the audited TimeSageWebSearch tool, but only if the scenario opts in
  * a custom final_answer(answer, report) tool to satisfy the evsandbox
    two-part response contract

Episode-history (cross-period feedback) is prepended to the task string,
so each period's run starts with a rolling summary of prior turns.
smolagents' own multi-step memory operates within a single period.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

from smolagents import CodeAgent

from .tools import CompactMemoryTool, TimeSageFinalAnswer, TimeSageWebSearch

# smolagents' stock CodeAgent system prompt teaches the Thought/Code/Observation
# format through ~5k characters of examples built on tools this agent does not
# have (web_search, image_qa, translator, ...). They are re-sent on every step.
# _system_prompt() swaps them for one example in this benchmark's own terms.
_EXAMPLES_START = "Here are a few examples using notional tools:"
_EXAMPLES_END = ("Above examples were using notional tools that might not exist for "
                 "you. On top of performing computations in the Python code snippets "
                 "that you create, you only have access to these tools")
_OWN_EXAMPLE = """Here is an example of the format:
---
Task: "Report the latest value of `level` in timeseries.csv and whether it is above 50."

Thought: I will read the CSV and look at its last row.
{{code_block_opening_tag}}
import pandas as pd
df = pd.read_csv("timeseries.csv")
print(df.tail(3))
{{code_block_closing_tag}}
Observation:
   period  level
40 2024-03   48.1
41 2024-04   51.7

Thought: The latest level is 51.7, above 50. I will submit the answer and a short report.
{{code_block_opening_tag}}
final_answer(answer={"above_50": True, "report": "In 2024-04 the level was 51.7, above 50."},
             report="In 2024-04 the level was 51.7, above 50.")
{{code_block_closing_tag}}
---

On top of performing computations in the Python code snippets that you create, you only have access to these tools"""


def _system_prompt() -> Optional[dict]:
    """smolagents' CodeAgent prompt templates with the stock examples replaced,
    or None (keep smolagents' own) if a newer template no longer has them."""
    import importlib.resources
    import yaml
    templates = yaml.safe_load(importlib.resources.files("smolagents.prompts")
                               .joinpath("code_agent.yaml").read_text())
    sp = templates["system_prompt"]
    i, j = sp.find(_EXAMPLES_START), sp.find(_EXAMPLES_END)
    if i < 0 or j < i:
        return None
    templates["system_prompt"] = sp[:i] + _OWN_EXAMPLE + sp[j + len(_EXAMPLES_END):]
    return templates


TRUNC_LIMIT = 4000


def _cap_str(v: Any) -> Any:
    if isinstance(v, str) and len(v) > TRUNC_LIMIT:
        return v[:TRUNC_LIMIT] + f"…[truncated {len(v) - TRUNC_LIMIT} chars]"
    return v


def _step_dict_to_row(step_dict: dict, turn: int) -> dict:
    """Convert one smolagents step (dict form) to a TimeSage trace row.

    Single source of truth — both the streaming step_callback and the
    end-of-run trace export route through this. Keeps on-disk and
    in-memory traces byte-identical for successful runs.
    """
    if "task" in step_dict:
        return {"turn": turn, "kind": "task",
                "task": step_dict.get("task") or ""}
    if "plan" in step_dict:
        return {"turn": turn, "kind": "plan",
                "plan": step_dict.get("plan") or ""}
    row: dict = {"turn": turn, "kind": "action",
                 "step_number": step_dict.get("step_number")}
    for fld in ("model_output", "code_action", "observations",
                "action_output", "error"):
        v = step_dict.get(fld)
        if v is None:
            continue
        if not isinstance(v, (str, int, float, bool, list, dict)):
            v = repr(v)
        if fld in ("observations", "action_output") and isinstance(v, str):
            v = _cap_str(v)
        row[fld] = v
    if step_dict.get("is_final_answer"):
        row["is_final_answer"] = True
    tu = step_dict.get("token_usage")
    if tu:
        row["token_usage"] = {
            "input_tokens":  tu.get("input_tokens"),
            "output_tokens": tu.get("output_tokens"),
        }
    return row


class _TraceWriter:
    """Append-only JSONL writer for streaming a trace to disk.

    Each step_callback invocation grabs the lock, increments the turn
    counter, formats one row, and fsyncs. If the subprocess gets killed
    mid-run, everything up to the last completed step is on disk.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        # Seed turn counter from existing rows in the file (worker may have
        # written `worker_start`, `task`, `phase` rows before constructing
        # this writer). Append-only — never truncate.
        path.parent.mkdir(parents=True, exist_ok=True)
        self._turn = 0
        if path.exists():
            try:
                self._turn = sum(1 for _ in path.open())
            except OSError:
                self._turn = 0
        else:
            path.write_text("")

    def emit(self, row: dict) -> None:
        with self._lock:
            self._turn += 1
            row = {"turn": self._turn, **{k: v for k, v in row.items()
                                          if k != "turn"}}
            with self.path.open("a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                try:
                    import os as _os
                    _os.fsync(f.fileno())
                except OSError:
                    pass

    def emit_step(self, step_obj: Any) -> None:
        # step_obj is a smolagents MemoryStep instance (ActionStep, etc.)
        # — `.dict()` returns the same shape we consume at end-of-run.
        try:
            d = step_obj.dict() if hasattr(step_obj, "dict") else {}
        except Exception:                                              # noqa: BLE001
            d = {}
        self.emit(_step_dict_to_row(d, turn=0))   # turn rewritten by emit()


# Curated whitelist. We intentionally exclude urllib/requests/socket so
# the model is forced to use web_search (audited) rather than raw HTTP.
DEFAULT_AUTHORIZED_IMPORTS = [
    "pandas", "numpy",
    "json", "csv", "re", "math", "statistics",
    "datetime", "pathlib", "io", "collections", "itertools", "functools",
    "pypdf",
]


def scenario_requires_web_search(scenario) -> bool:
    tags = list(getattr(scenario, "question_tags", []) or [])
    if "requires_web_search" in tags:
        return True
    sid = getattr(scenario, "scenario_id", "") or ""
    return sid == "iata_air_passenger_monthly_analytical"


def _build_instructions(scenario, requires_web_search: bool,
                        episode_history: list[dict]) -> str:
    required_keys = list(scenario.answer_schema.get("required") or [])
    web_blurb = ""
    if requires_web_search:
        web_blurb = (
            "\n* web_search(query: str, n: int=5) — audited, time-isolated. "
            "Use this for any web context; raw HTTP is not available."
        )
    history_blurb = ""
    if episode_history:
        parts = ["", "## Episode history (your past evaluations on this scenario)"]
        for turn in reversed(episode_history):                     # newest first
            rendered = turn.get("rendered") or ""
            if rendered:
                parts.append(rendered)
        parts.append(
            "Use the feedback above to improve this turn's answer."
        )
        history_blurb = "\n".join(parts)
    imports_blurb = ", ".join(DEFAULT_AUTHORIZED_IMPORTS)
    return (
        f"You are a markets/data analyst. All files you need are in the "
        f"CURRENT WORKING DIRECTORY (use `pathlib.Path.cwd()`; do not "
        f"assume an absolute path like /root — it does not exist). The "
        f"cwd contains:\n"
        f"  * timeseries.csv          — the historical data series\n"
        f"  * answer_schema.json      — required JSON shape for your answer\n"
        f"  * gt_source/<prior>.*     — prior-period reports (PDF/HTML/JSON)\n"
        f"\n"
        f"Available tools:\n"
        f"  * Python code execution. CRITICAL FORMAT: open every code block "
        f"with the EXACT tag `<code>` and close with `</code>` (XML-style, "
        f"NOT markdown). The smolagents parser only matches these tags — "
        f"a ```py``` fence, a ```python``` fence, or `<Code>`/`<CODE>` "
        f"with different casing or any extra whitespace inside the angle "
        f"brackets all fail to parse and cost a step. Example:\n"
        f"        <code>\n"
        f"        import pandas as pd\n"
        f"        df = pd.read_csv('timeseries.csv')\n"
        f"        print(df.tail())\n"
        f"        </code>\n"
        f"    Results from the executor are returned in the next observation.\n"
        f"  * final_answer(answer=<dict>, report=<str>) — submit your final "
        f"output. YOU MUST CALL THIS TOOL exactly once to finish. Do NOT "
        f"write the answer to a file. Do NOT emit a final textual reply "
        f"instead of calling the tool — the only way to be scored is to "
        f"call final_answer.{web_blurb}\n"
        f"\n"
        f"## Sandbox rules (the Python executor enforces these — violating "
        f"them wastes a step on an error)\n"
        f"\n"
        f"Authorized imports (everything else raises InterpreterError):\n"
        f"  {imports_blurb}\n"
        f"\n"
        f"Forbidden builtins: `open`, `eval`, `exec`, `compile`, "
        f"`__import__`, `globals`, `locals`. Forbidden modules include "
        f"`os`, `sys`, `subprocess`, `socket`, `urllib`, `requests`.\n"
        f"\n"
        f"File / IO replacements (use these instead of `open()`):\n"
        f"  * Read text:  `Path('x.txt').read_text()`\n"
        f"  * Read JSON:  `json.loads(Path('x.json').read_text())`\n"
        f"  * Read CSV:   `pd.read_csv('x.csv')`   (pandas handles IO "
        f"internally — pass a string path)\n"
        f"  * Read PDF:   `from pypdf import PdfReader; "
        f"PdfReader('x.pdf').pages[0].extract_text()`\n"
        f"  * Write text: `Path('out').write_text(...)`\n"
        f"  * List dir:   `[p.name for p in Path.cwd().iterdir()]`\n"
        f"  * Check path: `Path('x').exists()`\n"
        f"\n"
        f"Scenario tier: {scenario.tier}\n"
        f"Required answer keys (every one of these must be a key of the "
        f"dict you pass as `answer=`): {required_keys}\n"
        f"\n"
        f"Memory management (OPTIONAL — multi-period episode only):\n"
        f"  If you sense your conversation memory is getting bloated "
        f"(lots of failed code attempts, long observations no longer "
        f"needed, patterns you've already learned), you may call the "
        f"`request_memory_compaction(reason=...)` tool. The framework "
        f"will summarize what you've learned across past periods AFTER "
        f"the current period finishes, then reset your memory to that "
        f"summary before the next period. The tool returns immediately "
        f"with `scheduled: true` — it does NOT abort the current period. "
        f"Typical cadence: once every ~5 periods. Don't call this if "
        f"you're answering a single-period task.\n"
        f"\n"
        f"Task rules:\n"
        f"  1. Read the CSV (and prior-period gt_source files if needed) "
        f"using `pd.read_csv(Path.cwd() / 'timeseries.csv')` — do not "
        f"hallucinate values.\n"
        f"  2. Never cite or read the CURRENT period's gt_source — only "
        f"prior periods.\n"
        f"  3. Your final answer dict must contain exactly the required "
        f"keys. Your report must cite specific CSV cells or prior-period "
        f"files.\n"
        f"  4. End your run by calling final_answer(answer=..., report=...). "
        f"Nothing else terminates the loop."
        f"{history_blurb}"
    )


class TimeSageSmolAgent:
    """Wraps a smolagents CodeAgent. Exposes (.run(prompt) → structured, report, trace)."""

    def __init__(self, scenario, model, *,
                 audit_path: Optional[Path] = None,
                 cutoff: Optional[str] = None,
                 episode_history: Optional[list[dict]] = None,
                 max_steps: int = 12,
                 verbosity_level: int = 0,
                 stream_trace_path: Optional[Path] = None):
        self.scenario = scenario
        self.episode_history = list(episode_history or [])
        self._final = TimeSageFinalAnswer()
        self._compact = CompactMemoryTool()
        self._websearch: Optional[TimeSageWebSearch] = None
        tools: list = [self._final, self._compact]
        self._requires_web = scenario_requires_web_search(scenario)
        if self._requires_web:
            self._websearch = TimeSageWebSearch(
                cutoff=cutoff or "", audit_path=audit_path,
            )
            tools.append(self._websearch)
        instructions = _build_instructions(scenario, self._requires_web,
                                           self.episode_history)
        # Streaming trace writer: callback fires once per ActionStep
        # completion. Survives SIGKILL because every row is fsync'd.
        self._writer: Optional[_TraceWriter] = None
        step_callbacks: list = []
        if stream_trace_path is not None:
            self._writer = _TraceWriter(Path(stream_trace_path))
            step_callbacks.append(self._on_step)
        self.prompt_templates = _system_prompt()     # None: smolagents' stock prompt
        self._agent = CodeAgent(
            tools=tools,
            model=model,
            prompt_templates=self.prompt_templates,
            additional_authorized_imports=DEFAULT_AUTHORIZED_IMPORTS,
            instructions=instructions,
            max_steps=max_steps,
            verbosity_level=verbosity_level,
            add_base_tools=False,
            step_callbacks=step_callbacks or None,
        )

    def _on_step(self, step, agent=None):
        if self._writer is not None:
            self._writer.emit_step(step)

    def memory_len(self) -> int:
        return len(self._agent.memory.steps)

    def usage_since(self, n_steps: int) -> dict:
        """Tokens spent by the memory steps after the first `n_steps`.

        In episode mode memory accumulates across periods, so the run's own
        token_usage would count earlier periods too; this counts one period.
        """
        inp = out = 0
        for step in self._agent.memory.steps[n_steps:]:
            tu = getattr(step, "token_usage", None)
            if tu is not None:
                inp += getattr(tu, "input_tokens", 0) or 0
                out += getattr(tu, "output_tokens", 0) or 0
        return {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out}

    def set_period_cutoff(self, period: str) -> None:
        """Update the agent's web-search cutoff to the current period.

        In interactive episode mode this must be called BEFORE each
        period's `agent.run()` so `web_search` enforces time isolation
        against THAT period's release, not the episode's last period.
        Safe no-op for scenarios that don't expose web search.
        """
        if self._websearch is not None:
            self._websearch._cutoff = period

    def run(self, prompt: str) -> tuple[dict, str, list[dict], dict]:
        """Returns (structured_answer, report, trace, usage_summary)."""
        # Note: worker.py seeds the {kind: task} row before us so it's on
        # disk even if model construction blocks. We don't re-emit here.
        result = self._agent.run(prompt, return_full_result=True)

        structured = self._final.captured.get("answer") or {}
        if not isinstance(structured, dict):
            try:
                structured = json.loads(structured)
            except Exception:                                       # noqa: BLE001
                structured = {}
        report = self._final.captured.get("report") or ""
        # Fall back to RunResult.output if the model emitted a final_answer
        # but smolagents intercepted it before our tool ran. Rare but
        # defensive — keeps the response non-empty.
        if not structured and isinstance(result.output, dict):
            structured = result.output.get("answer") or result.output

        trace = self._steps_to_trace(result.steps)
        usage = self._extract_usage(result)
        final_state_row = {"turn": -1, "kind": "final_state",
                           "state": str(result.state),
                           "wall_s": getattr(result.timing, "duration", None)}
        if usage:
            usage_row = {"turn": -1, "kind": "lm_usage_aggregate",
                         "usage": usage}
            trace.append(usage_row)
            if self._writer is not None:
                self._writer.emit(usage_row)
        trace.append(final_state_row)
        if self._writer is not None:
            self._writer.emit(final_state_row)
        return structured, report, trace, usage

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _steps_to_trace(steps: list[Any]) -> list[dict]:
        """Convert smolagents step dicts (from RunResult.steps) to trace rows.

        Routes through the module-level _step_dict_to_row so the on-disk
        streamed rows and the in-memory rows have identical formatting.

        Truncation policy: task / plan / model_output / code_action are
        preserved in full — they're the canonical record of what the agent
        thought and ran. Only `observations` and `action_output` are
        capped at TRUNC_LIMIT chars (they can balloon when a tool returns
        a large blob, e.g., a CSV dump).
        """
        out: list[dict] = []
        for i, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                out.append({"turn": i, "kind": "unknown",
                            "repr": repr(step)[:200]})
                continue
            out.append(_step_dict_to_row(step, turn=i))
        return out

    def compact_memory(self, periods_done: list[str],
                       per_period_answers: list[dict]) -> Optional[dict]:
        """Summarize the agent's accumulated memory and reset it to a
        single TaskStep containing the summary.

        Called between TimeSage episode periods to keep the conversation
        from blowing past the model's context window. Implementation:

          1. Extract the agent's memory in summary_mode (drops model_output
             traces, keeps tool calls + observations).
          2. Build a structured summarizer prompt with explicit pointers
             (period answers seen so far, structural facts, error patterns
             to avoid).
          3. Call the same underlying LM with that prompt to get a
             1.5K-token bullet summary.
          4. Reset memory and inject the summary as a single TaskStep so
             the next `agent.run(reset=False)` starts fresh but carries
             forward what was learned.

        Returns a dict {"summary": str, "tokens_in": int, "tokens_out": int,
        "steps_before": int, "steps_after": int} or None on failure.
        """
        from smolagents.memory import TaskStep                          # noqa: WPS433
        from smolagents.models import ChatMessage, MessageRole          # noqa: WPS433

        steps_before = len(self._agent.memory.steps)
        if steps_before == 0:
            return None

        # 1. Compact-mode transcript (model_output stripped automatically)
        try:
            msgs = self._agent.write_memory_to_messages(summary_mode=True)
        except Exception as exc:                                        # noqa: BLE001
            return {"summary": "", "error": f"write_memory failed: {exc!r}",
                    "steps_before": steps_before, "steps_after": steps_before}

        def _msg_text(m) -> str:
            c = m.content
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return "\n".join(part.get("text", "") if isinstance(part, dict) else str(part)
                                  for part in c)
            return str(c)

        TRANSCRIPT_CAP = 60_000   # chars; ~15K tokens conservative
        parts = []
        running = 0
        for m in msgs:
            role = m.role.value if hasattr(m.role, "value") else str(m.role)
            text = _msg_text(m)
            block = f"\n[{role}]\n{text}"
            if running + len(block) > TRANSCRIPT_CAP:
                parts.append(block[: TRANSCRIPT_CAP - running])
                parts.append("\n…[transcript truncated for summarizer]")
                break
            parts.append(block)
            running += len(block)
        transcript = "".join(parts)

        # 2. Period-answer block — short, structured
        ans_lines = []
        for i, ans in enumerate(per_period_answers):
            label = periods_done[i] if i < len(periods_done) else f"period#{i}"
            ans_str = json.dumps(ans, ensure_ascii=False, default=str)[:400]
            ans_lines.append(f"  - {label}: {ans_str}")
        ans_block = "\n".join(ans_lines) if ans_lines else "(none recorded)"

        scenario_id = getattr(self.scenario, "scenario_id", "?")
        tier = getattr(self.scenario, "tier", "?")
        required_keys = list(self.scenario.answer_schema.get("required") or [])

        summarizer_prompt = (
            f"You are a CONTEXT COMPRESSOR for a long-running multi-period "
            f"analysis agent. The agent has completed {len(periods_done)} "
            f"periods of scenario `{scenario_id}` (tier={tier}) and the "
            f"conversation is about to overflow the model's context window. "
            f"Produce a tight summary the agent will read INSTEAD of its full "
            f"chat history before the next period.\n"
            f"\n"
            f"## Periods completed (oldest → newest)\n"
            f"{periods_done}\n"
            f"\n"
            f"## Structured answers the agent already submitted\n"
            f"{ans_block}\n"
            f"\n"
            f"## Required answer keys for THIS scenario (every period)\n"
            f"{required_keys}\n"
            f"\n"
            f"## Compacted transcript so far (summary mode — already drops "
            f"the model's internal thinking; tool calls + observations remain)\n"
            f"{transcript}\n"
            f"\n"
            f"## What your summary MUST cover (be terse, use bullets, "
            f"~1500 tokens max):\n"
            f"1. **Data layout** — the exact CSV column names + indexing "
            f"pattern the agent has been using (so it doesn't have to "
            f"re-discover).\n"
            f"2. **Working code idioms** — concrete snippets that have "
            f"successfully read files (e.g. `pd.read_csv('timeseries.csv')`); "
            f"and explicit DON'Ts (e.g. `open()` is sandboxed, `os` is not "
            f"importable).\n"
            f"3. **Answer-schema gotchas** — fields that have been tricky "
            f"to fill correctly, units, enum value choices, etc.\n"
            f"4. **Feedback patterns** — what the judge has been "
            f"penalizing (incomplete event lists, missing direction, etc.) "
            f"and how the agent should adjust.\n"
            f"5. **One-line recap per past period**: what the answer was "
            f"and whether it was correct/incorrect (if feedback was given).\n"
            f"\n"
            f"Return ONLY the summary body — no preamble, no closing line. "
            f"Plain markdown, no code fences around the whole thing."
        )

        # 3. Single LM call. Use the agent's own model so we don't add a
        # new dependency; the model API surface is `generate(messages)`.
        try:
            req_msg = ChatMessage(
                role=MessageRole.USER,
                content=[{"type": "text", "text": summarizer_prompt}],
            )
            resp = self._agent.model.generate(messages=[req_msg],
                                               stop_sequences=None)
            summary_text = _msg_text(resp)
        except Exception as exc:                                        # noqa: BLE001
            return {"summary": "", "error": f"summarize call failed: {exc!r}",
                    "steps_before": steps_before, "steps_after": steps_before,
                    "summarizer_prompt_chars": len(summarizer_prompt)}

        tu = getattr(resp, "token_usage", None)
        tokens_in  = getattr(tu, "input_tokens",  None) if tu else None
        tokens_out = getattr(tu, "output_tokens", None) if tu else None

        # 4. Replace memory with a single TaskStep that the next period
        # will see as its "prior context".
        self._agent.memory.reset()
        carry_task = (
            f"# Compressed history — first {len(periods_done)} periods "
            f"of scenario `{scenario_id}`\n\n"
            f"{summary_text}\n\n"
            f"---\n"
            f"You will now continue with the NEXT period. The sandbox "
            f"files in cwd have been re-materialized for that period. "
            f"Everything you learned above still applies; you do NOT "
            f"need to re-discover the CSV layout or re-test which builtins "
            f"are sandboxed."
        )
        self._agent.memory.steps.append(TaskStep(task=carry_task))

        return {
            "summary":      summary_text,
            "tokens_in":    tokens_in,
            "tokens_out":   tokens_out,
            "steps_before": steps_before,
            "steps_after":  len(self._agent.memory.steps),
            "transcript_chars_sent": len(transcript),
        }

    @staticmethod
    def _extract_usage(result: Any) -> dict:
        tu = getattr(result, "token_usage", None)
        if tu is None:
            return {}
        return {
            "provider":      "smolagents",
            "input_tokens":  getattr(tu, "input_tokens", None),
            "output_tokens": getattr(tu, "output_tokens", None),
            "total_tokens":  ((getattr(tu, "input_tokens", 0) or 0) +
                              (getattr(tu, "output_tokens", 0) or 0)),
        }
