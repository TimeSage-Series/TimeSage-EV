# TimeSage Agent Contract

Agents in this directory are evaluated by [`evsandbox`](../evsandbox/). Each
agent is an independent Python package (or any executable, really) that
implements the contract below. The environment doesn't care how an agent
plans, what LM it uses, or what tools it instantiates internally — it only
cares that the subprocess JSON-stdio contract is honored.

## Invocation

`evsandbox` spawns each agent with:

* **cwd** = the sandbox `/root` directory (contains `timeseries.csv`,
  `answer_schema.json`, `gt_source/<prior>.{pdf,html}`).
* **env** = a restricted set:
  * `PATH`, `HOME` — bare minimum.
  * `PYTHONPATH` — wired so `evsandbox` and `evbench.evaluator` import cleanly.
  * `TIMESAGE_CUTOFF` — period string, e.g. `"2024-05"`.
  * `TIMESAGE_RUN_ID` — opaque correlation id.
  * `TIMESAGE_AUDIT_PATH` — present iff a network audit log is expected.
  * `TIMESAGE_SEARXNG` — present iff the scenario opts into web search.
  * `ANTHROPIC_API_KEY` — forwarded iff the parent has it set.
* **stdin** = one JSON line (the `AgentRequest`).
* **stdout** = one JSON line (the `AgentResponse`); if multiple lines are
  written, the last one wins.
* **stderr** = preserved by the env to `runs/<run_id>/stderr.log`.

## Wire schema

Source of truth: [`evsandbox/evsandbox/protocol.py`](../evsandbox/evsandbox/protocol.py).

```jsonc
// Request — written to the agent's stdin
{
  "scenario_dir": "/abs/path/to/evbench/scenarios/.../my_scenario",
  "period":       "2024-05",
  "prompt":       "<rephrased natural-language user prompt>",
  "agent_args":   { "lm_model": "claude-sonnet-4-6", "seed": 0 },

  // Empty in independent-mode sweep; populated in episode mode with the
  // ordered list of feedback from PRIOR periods of THIS scenario only.
  "episode_history": [
    {
      "period": "2024-04",
      "aggregate": 0.62,
      "passed": false,
      "axis_scores": { "keypoint_accuracy": 60.0, "keypoint_coverage": 100.0, ... },
      "structured_answer": { ... },        // your own past answer (echo)
      "keypoint_results": [
        { "id": "kp_dominant_activity", "passed": true },
        { "id": "kp_wow_change", "passed": false,
          "agent_value": 12, "gt_value": 18 }    // detailed mode only
      ],
      "faithfulness_notes": [ "speculation: …" ],
      "rendered": "Period 2024-04: FAILED (aggregate=0.62)\n  Axis scores: …"
    }
  ]
}

// Response — written to the agent's stdout
{
  "status":            "ok",
  "structured_answer": { "ao_phase": "Neutral", "as_of_month": "2024-05" },
  "report":            "In 2024-05 the headline indicator …",
  "trace":             [ { "turn": 0, "kind": "user", "..." }, ... ],
  "wall_ms":           1287,
  "error":             null
}
```

In episode mode (`evsandbox episode`, `sweep --mode episode`) the agent
process stays alive across all periods and the parent sends one message per
period, `{"period": ..., "cutoff": ..., "prompt": ...}`
(see [`protocol.py`](../evsandbox/evsandbox/protocol.py)). Env vars are fixed
at spawn, so `TIMESAGE_CUTOFF` starts at the first period's cutoff; the agent
must apply each message's `cutoff` before working on that period —
`evsandbox.protocol.apply_period_cutoff(msg)` does it. `--timeout` is a
per-period budget, counted from when the period message is sent. When a
period message arrives, the runner has already refreshed the working
directory to that period (`timeseries.csv`, `answer_schema.json`,
`gt_source/`); other files the agent wrote there are kept.

`episode_history` is ordered oldest-first. Each entry refers to a period
strictly < the current request's `period` (env enforces this). The
`rendered` field is a ready-to-prepend human-readable summary; agents that
want finer control can read the structured fields and render themselves.

Status sentinels: `ok` (full success), `incomplete` (ran but missing
`structured_answer` or `report`), `agent_crash` (uncaught exception). The
environment may overwrite these with `agent_timeout` or `leakage_detected`
based on parent-side checks, but the agent itself should only emit the
first three.

## Optional facilities provided by `evsandbox`

Agents that want them can `import` from `evsandbox`:

* `evsandbox.network.search_with_isolation(query, n, cutoff, audit_path)` —
  three-layer time-isolated web search (SearXNG → Common Crawl CDX →
  Wayback Machine). Writes one audit row per call.

Agents that prefer their own retrieval stack are welcome to skip this and
issue HTTP directly. Either way, **the agent must not access content
created after `cutoff - 7 days`**; the env's post-run audit will flag
violations.

## Registering an agent

Drop a new directory under `agents/<name>/` with:

```
agents/<name>/
├── pyproject.toml
└── <name>/
    └── worker.py          # entry: `python -m <name>.worker`
```

Invoke via `evsandbox run … --agent-cmd "python -m <name>.worker"` (or
register an alias in `evsandbox.cli.AGENT_ALIASES`).

## Reference implementations

* [`agents/smolagents_agent/`](smolagents_agent/) — a smolagents CodeAgent:
  the LM writes Python to read the sandbox files, calls the time-isolated web
  search as a tool, and keeps memory across the periods of an episode.
* [`agents/timesage_agent/`](timesage_agent/) — `smolagents_agent` plus a
  per-sweep skill library: functions saved in one period become live tools
  in the next.

Use `smolagents_agent` as a template when building new agents.
