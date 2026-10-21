# Agent Contract

`evsandbox` runs each agent as a subprocess and talks to it in JSON lines over
stdin/stdout. Any language or framework works; only this contract matters.
The source of truth is [`evsandbox/evsandbox/protocol.py`](../evsandbox/evsandbox/protocol.py).

## Environment

- **cwd** — the period's sandbox: `timeseries.csv`, `answer_schema.json`, and
  earlier periods' reports under `gt_source/`.
- **env** — `PATH`, `HOME`, `PYTHONPATH`, plus:
  - `TIMESAGE_CUTOFF` — the period, e.g. `2024-05`
  - `TIMESAGE_RUN_ID` — an opaque id
  - `TIMESAGE_TRACE_PATH` — a JSONL file to append trace rows to, so a partial
    trace survives a timeout
  - `TIMESAGE_SEARXNG`, `TIMESAGE_AUDIT_PATH` — only when the scenario opts
    into web search
  - model credentials the parent has set: `ANTHROPIC_API_KEY`,
    `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `SELF_HOSTED_BASE_URL`,
    `SELF_HOSTED_API_KEY`, proxy variables
- **stderr** — saved to `stderr.log` in the run directory.

## Single period — `evsandbox run`, `sweep`

One request on stdin, one response on stdout (the last line wins), then exit.

```jsonc
// request
{"scenario_dir": "/abs/path/to/scenario", "period": "2024-05",
 "prompt": "<task, input, question and answer format>",
 "agent_args": {"lm_provider": "anthropic", "lm_model": "claude-sonnet-4-6"}}

// response
{"status": "ok",                         // ok | incomplete | agent_crash
 "structured_answer": {"ao_phase": "Neutral"},   // matches answer_schema.json
 "report": "<markdown>",
 "trace": [ ... ], "wall_ms": 1287, "error": null}
```

## Episode — `evsandbox episode`, `sweep --mode episode`

The process stays alive for all of a scenario's periods, so the agent can
carry memory from one period to the next.

```jsonc
→ {"scenario_dir": ..., "agent_args": {...},
   "episode": {"interactive": true, "episode_dir": "...", "periods": ["p1", "p2", ...]}}
// for each period:
→ {"period": "p1", "cutoff": "p1", "prompt": "..."}
← {"period": "p1", "status": "ok", "structured_answer": {...}, "report": "...",
   "wall_ms": 0, "usage": {"input_tokens": 0, "output_tokens": 0}}
// at the end:
→ {"done": true}
← {"status": "ok", "mode": "episode", "periods": [...], "wall_ms": 0}
```

- Feedback on the previous period, when `--feedback-mode` is not `none`, is
  prepended to the next period's `prompt`.
- The runner refreshes cwd to each period before sending its message.
- Env vars are fixed at spawn, so apply each message's `cutoff` yourself:
  `evsandbox.protocol.apply_period_cutoff(msg)`.
- `--timeout` is per period.

The runner may replace the agent's status with `agent_timeout` or
`leakage_detected`.

## Web search

`evsandbox.network.search_with_isolation(query, n, cutoff, audit_path)` is a
time-isolated search an agent may import. Whatever an agent uses, it must not
read content published after `cutoff - 7 days`.

## Adding an agent

```
agents/<name>/
├── pyproject.toml
└── <name>/worker.py        # python -m <name>.worker
```

Run it with `--agent-cmd "python -m <name>.worker"`, or register an alias in
`evsandbox.cli.AGENT_ALIASES`. [`smolagents_agent`](smolagents_agent/) is the
template to start from; [`timesage_agent`](timesage_agent/) shows how to
extend it.
