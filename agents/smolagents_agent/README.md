# smolagents_agent — TimeSage agent built on smolagents

A TimeSage agent that uses HuggingFace's [`smolagents`][smolagents] CodeAgent
for the orchestration loop: Python-as-action, multi-step ReAct, tool calls
visible in the trace, and memory that accumulates across periods of a
TimeSage episode. Implements the JSON-stdio contract in
[`agents/README.md`](../README.md) and the interactive episode loop in
[`evsandbox.protocol`](../../evsandbox/evsandbox/protocol.py).

[smolagents]: https://github.com/huggingface/smolagents


## How to invoke

Single period (`evsandbox run`):

```bash
evsandbox run evbench/scenarios/easy/finance/cboe_vix_volatility_regime_state 2026-W04 \
  --agent smolagents_agent \
  --agent-arg lm_provider=spike \
  --agent-arg lm_model=Kimi-K2.6 \
  --agent-arg max_tokens=32768 \
  --agent-arg max_steps=8 \
  --target test-turn1 \
  --timeout 600
```

Interactive episode with feedback between periods + agent-decided memory
compaction + an LLM judge (Claude Code CLI):

```bash
evsandbox episode evbench/scenarios/easy/climate/noaa_cpc_ao_monthly_phase \
  --agent smolagents_agent \
  --agent-arg lm_provider=spike \
  --agent-arg lm_model=Kimi-K2.6 \
  --agent-arg max_tokens=32768 \
  --agent-arg max_steps=10 \
  --agent-arg memory_policy=agent_decides \
  --feedback-mode score \
  --judge claude_cli --judge-thinking middle \
  --target gas-middle-agent-decides \
  --timeout 2400
```


## Architecture

```
evsandbox runner                      smolagents_agent subprocess
  │                                    │
  │  AgentRequest (stdin JSON)         │  worker.main() — dispatches:
  ├───────────────────────────────────►│    _run_single  for `evsandbox run`
  │                                    │    _run_episode for `evsandbox episode`
  │                                    │       │
  │                                    │       ▼
  │                                    │  TimeSageSmolAgent
  │                                    │    wraps smolagents.CodeAgent
  │                                    │    tools:
  │                                    │      • TimeSageFinalAnswer
  │                                    │      • CompactMemoryTool
  │                                    │      • TimeSageWebSearch  (conditional)
  │                                    │    callbacks:
  │                                    │      • _on_step  → streaming TraceWriter
  │  AgentResponse (stdout JSON)       │
  │◄───────────────────────────────────┤
```

The agent never spawns its own sandbox; cwd is set by the runner to a
tempdir containing `timeseries.csv`, `answer_schema.json`, and prior-period
files under `gt_source/`. In interactive episode mode the runner refreshes
this cwd to each period before sending its message; the worker only reads it.


## Tools the agent has

### 1. `final_answer(answer, report)` — required, terminates the period

The mandatory exit. Captures two arguments: a JSON-serialisable `answer`
dict matching the scenario's `answer_schema.json`, and a markdown `report`
string. Calling it stops the smolagents loop. See
[`tools.py:TimeSageFinalAnswer`](smolagents_agent/tools.py).

### 2. `request_memory_compaction(reason=...)` — optional, episode mode only

Lets the agent schedule a memory compaction for AFTER the current period
finishes. Returns immediately with `{"scheduled": true, ...}`. The
framework checks the tool's `requested` flag at the period boundary;
if true, runs `agent.compact_memory(...)` and resets the flag.

This is the smolagents-idiomatic way to expose an agent-controlled
capability — the agent's decision appears as a regular `tool_call` step
in the trace, not as a string in the report.

The agent only sees this tool when `memory_policy ∈ {agent_decides, hybrid}`
… actually it always sees it (the tool is always registered), but in
`memory_policy=none` calls are recorded but ignored.

### 3. `web_search(query, n)` — conditional, time-isolated

Only registered when the scenario opts into web search
(see [`agent.py:scenario_requires_web_search`](smolagents_agent/agent.py)).
Delegates to `evsandbox.network.search_with_isolation`, which enforces
the cutoff via CDX/Wayback and writes an audit row.


## Python sandbox imports

The smolagents `LocalPythonExecutor` enforces a strict allowlist. Builtins
like `open`, `eval`, `exec`, `__import__`, `globals`, `locals` are
blocked; modules like `os`, `sys`, `subprocess`, `socket`, `urllib`,
`requests` are blocked.

What's whitelisted (`DEFAULT_AUTHORIZED_IMPORTS` in
[`agent.py`](smolagents_agent/agent.py)):

```
pandas, numpy,
json, csv, re, math, statistics,
datetime, pathlib, io, collections, itertools, functools,
pypdf
```

The agent's system prompt explicitly lists the canonical replacements
(`Path(x).read_text()` for `open`, `pd.read_csv(...)` works because
pandas opens files internally — outside the sandbox).


## `agent_args` knobs

Passed via `--agent-arg key=value` (repeatable). Values that parse as
JSON are decoded as such; otherwise treated as strings.

### LM selection

| Key            | Default     | Notes |
| ---            | ---         | ---   |
| `lm_provider`  | (auto)      | `spike` / `openai_compat` / `openai` / `anthropic` / empty (auto-detect from `lm_model`) |
| `lm_model`     | (required)  | SPIKE slug (e.g. `Kimi-K2.6`), OpenAI model id, or `mock` |
| `lm_base_url`  | (provider-dependent) | for `openai_compat` only |
| `lm_api_key`   | (env)       | falls back to `SPIKE_API_KEY` / `OPENAI_API_KEY` |
| `max_tokens`   | 4096        | LM's `max_tokens` (the output budget — DOES NOT include input) |
| `temperature`  | 0.0         | |
| `timeout`      | 600         | per-LM-call timeout (seconds) |

For SPIKE, `lm_model` is a registry key — see
the registry configured via `TIMESAGE_MODELS_CONFIG` (see `.env.example`).

### Agent-loop control

| Key             | Default | Notes |
| ---             | ---     | ---   |
| `max_steps`     | 12      | smolagents' per-period step cap. Hit this and the episode-period ends as `incomplete`. |
| `verbosity`     | 0       | smolagents log verbosity (0=quiet, 3=full chain-of-thought) |

### Memory management (episode mode only)

| Key                              | Default  | Notes |
| ---                              | ---      | ---   |
| `memory_policy`                  | `none`   | one of `none` / `interval` / `agent_decides` / `hybrid` |
| `memory_compact_interval`        | 0        | for `interval`/`hybrid`: every N periods |
| `memory_compact_token_threshold` | 200000   | for `hybrid`: also compact when last-step input tokens exceed this |

See the next section for what each mode does.


## Memory policies — pick one

For long episodes (~10+ periods), the conversation accumulates linearly
and will eventually overflow the model's context window. We saw this in
practice: Kimi-K2.6 (256K window) crashed at period 8 of a 24-period
middle-tier episode with `input_tokens=229,377 + output_budget=32,768 >
262,144`.

The four policies are knobs on **when** to run the LM summarizer:

### `none` (default)

Never compact. Fine for short episodes (≤7 periods on middle tier with
Kimi). Predictable, no extra LM calls.

### `interval`

```bash
--agent-arg memory_policy=interval --agent-arg memory_compact_interval=5
```

Compact every K periods unconditionally. The framework decides; the agent
has no say.  Predictable cost (one summarizer call per K periods), but
sometimes wasteful (compacts when memory is still small).

### `agent_decides`

```bash
--agent-arg memory_policy=agent_decides
```

The agent calls `request_memory_compaction(reason=...)` when it senses
its memory is bloating. Worker checks the tool's flag after each period
and compacts if set. The agent's reason is recorded in the trace
(`memory_compact_start.agent_reason`).

**Pros**: zero waste — only compacts when the agent thinks it's helpful.
The decision is observable in the trace as a `tool_call` step.

**Cons**: agent might forget to ask and run into the context wall.
Use `hybrid` if that worries you.

### `hybrid` — recommended for long unfamiliar episodes

```bash
--agent-arg memory_policy=hybrid \
--agent-arg memory_compact_token_threshold=200000 \
--agent-arg memory_compact_interval=10
```

Compaction triggers on ANY of:
- agent called `request_memory_compaction` (primary)
- last-step input tokens estimate > `memory_compact_token_threshold` (safety net)
- every `memory_compact_interval` periods (fallback)

The trace `triggers` field lists which condition fired (a single compaction
can be triggered by multiple).


## How compaction works

[`agent.py:compact_memory`](smolagents_agent/agent.py) does this between periods:

1. Call `agent._agent.write_memory_to_messages(summary_mode=True)` — this
   uses smolagents' built-in summary representation that drops the
   model's `model_output` (internal chain-of-thought) but keeps tool
   calls + observations.
2. Build a structured summarizer prompt with 5 explicit sections (data
   layout, working code idioms, schema gotchas, feedback patterns,
   one-line per-period recap). Source: same `agent.py:compact_memory`.
3. Single LM call (same model the agent uses) to produce a ≤1500-token
   bullet summary.
4. `agent._agent.memory.reset()` to clear all steps.
5. Inject a single `TaskStep` carrying the summary as the next period's
   "prior context."

The compaction itself shows up in the streaming trace as
`memory_compact_start` / `memory_compact_done` rows with timing,
token-usage, and the summary character count. The full summary is also
written to disk at `<episode_dir>/compactions/after_period_NN_<period>.md`
for audit.


## Trace format

Each period emits an append-only `trace.jsonl` line per smolagents step,
plus extra rows at period boundaries:

```jsonc
// At worker startup (before any LM call)
{"kind": "worker_start", "ts": "...", "mode": "episode", "lm_model": "..."}
{"kind": "phase", "name": "build_model_start"}
{"kind": "phase", "name": "build_model_done", "model_id": "moonshotai/Kimi-K2.6"}

// Per period
{"kind": "period_start", "period": "2024-05", "is_first": true, "prompt_chars": 2804}
{"kind": "task",   "task": "<full prompt the agent received>", "period": "2024-05"}
{"kind": "action", "step_number": 1, "code_action": "import pandas...",
 "observations": "...", "token_usage": {"input_tokens": ..., "output_tokens": ...}}
{"kind": "action", "step_number": 2, "is_final_answer": true, ...}
{"kind": "lm_usage_aggregate", "usage": {"input_tokens": ..., "output_tokens": ..., "total_tokens": ...}}
{"kind": "final_state", "state": "success", "wall_s": 9.6}
{"kind": "period_done", "period": "2024-05", "status": "ok", "wall_ms": 9612}

// At period boundary if memory compaction fires
{"kind": "memory_compact_start", "after_period": "2024-09", "n_periods": 5,
 "policy": "agent_decides", "triggers": ["agent_marker"],
 "agent_reason": "memory has 20+ failed pandas attempts, pattern stable now",
 "last_input_tokens": 180000}
{"kind": "memory_compact_done", "wall_ms": 5400, "triggers": [...],
 "tokens_in": 14322, "tokens_out": 1276,
 "steps_before": 67, "steps_after": 1, "summary_chars": 6204}

// Or if a period in policy != "none" had no triggers
{"kind": "memory_compact_skipped", "after_period": "2024-06",
 "policy": "agent_decides", "last_input_tokens": 32000,
 "agent_requested": false}
```

The streaming TraceWriter (`agent.py:_TraceWriter`) fsyncs every line so
even if the subprocess is SIGKILL'd, everything up to the last completed
step survives on disk. The non-streaming `result.steps` returned by
smolagents is converted to the same row shape via
`agent.py:_step_dict_to_row` so on-disk and in-memory traces are byte-identical.


## Examples

### Comparing memory policies on the same scenario

```bash
# Baseline: no compaction → will likely crash mid-episode for middle/hard tier
evsandbox episode <scenario> --agent smolagents_agent \
  --agent-arg lm_model=Kimi-K2.6 --agent-arg memory_policy=none \
  --target compare-none

# Fixed interval: predictable cost
evsandbox episode <scenario> --agent smolagents_agent \
  --agent-arg lm_model=Kimi-K2.6 \
  --agent-arg memory_policy=interval \
  --agent-arg memory_compact_interval=5 \
  --target compare-interval

# Agent decides: zero-waste, fully visible in trace
evsandbox episode <scenario> --agent smolagents_agent \
  --agent-arg lm_model=Kimi-K2.6 --agent-arg memory_policy=agent_decides \
  --target compare-agent

# Hybrid: agent decides + auto safety net
evsandbox episode <scenario> --agent smolagents_agent \
  --agent-arg lm_model=Kimi-K2.6 \
  --agent-arg memory_policy=hybrid \
  --agent-arg memory_compact_token_threshold=180000 \
  --agent-arg memory_compact_interval=10 \
  --target compare-hybrid
```

Aggregate scores end up at
`exp/<target>/<llm-slug>/<tier>/<scenario>/episode_scores.json`;
the index `exp/<target>/_index.jsonl` lets you grep across runs.


## Source layout

```
agents/smolagents_agent/
├── pyproject.toml                    # deps: smolagents, openai, pandas, pypdf
├── README.md                         # this file
└── smolagents_agent/
    ├── __init__.py
    ├── tools.py                       # TimeSageFinalAnswer, CompactMemoryTool, TimeSageWebSearch
    ├── lm.py                          # build_model() — SPIKE registry + openai_compat + anthropic
    ├── agent.py                       # TimeSageSmolAgent: CodeAgent wrapper + compact_memory()
    └── worker.py                      # subprocess entrypoint (single + interactive episode modes)
```


## Limitations / known sharp edges

- **Per-period subprocess overhead in `evsandbox run`** but not in
  `episode` — episode mode keeps one subprocess alive for all periods so
  smolagents' `agent.run(reset=False)` actually reuses memory.
- **Streaming JSONL trace is append-only**: rotating it mid-run isn't
  supported. Long episodes can produce a few-hundred-KB `trace.jsonl`.
- **Sandbox is local-process, not Docker**. The smolagents executor
  enforces an import allowlist; this is process-level isolation, not
  container-level. Don't run agents from untrusted scenario authors.
- **`max_tokens` is the OUTPUT budget**, not total. With Kimi-K2.6's
  256K window you can safely set `max_tokens=32768` and still have
  ~230K input headroom. Watch for context overflow on `none` policy.
- **`pass_threshold`** is per-scenario and lives in
  `evbench/tasks/<…>/scoring.yaml` (top-level OR nested under
  `aggregation:`). The loader checks both. Every released scenario sets 0.8;
  if absent, the default is 80 (0-100 scale).
