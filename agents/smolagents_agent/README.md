# smolagents_agent

A baseline agent built on the [smolagents](https://github.com/huggingface/smolagents)
CodeAgent: the model writes Python to read the sandbox, and in episode mode
keeps its memory across periods.

## Usage

```bash
evsandbox run evbench/scenarios/easy/climate/noaa_cpc_ao_monthly_phase 2024-05 \
  --agent smolagents_agent \
  --agent-arg lm_provider=anthropic --agent-arg lm_model=claude-sonnet-4-6

evsandbox episode evbench/scenarios/easy/climate/noaa_cpc_ao_monthly_phase \
  --agent smolagents_agent \
  --agent-arg lm_provider=anthropic --agent-arg lm_model=claude-sonnet-4-6 \
  --agent-arg memory_policy=hybrid \
  --feedback-mode score --judge anthropic
```

## Tools

- `final_answer(answer, report)` — required; submits the period.
- `request_memory_compaction(reason)` — asks for memory to be summarised after
  the period; honoured under `agent_decides` and `hybrid`.
- `web_search(query, n)` — time-isolated search, only for scenarios that opt
  in.

Python runs in smolagents' local executor with an import allowlist (`pandas`,
`numpy`, `pypdf` and standard data modules); `open`, `os`, `subprocess` and
network modules are blocked.

## `agent_args`

| Key | Default | |
|---|---|---|
| `lm_provider` | required | `anthropic`, `openai`, `openrouter`, `self_hosted` |
| `lm_model` | required | model id; for `self_hosted`, a model the endpoint serves |
| `lm_base_url`, `lm_api_key` | env | override the provider's URL / key |
| `max_tokens` | 8192 | output budget per LM call |
| `temperature` | 0.0 | |
| `timeout` | 600 | seconds per LM call |
| `max_steps` | 12 | steps per period; hitting it ends the period as `incomplete` |
| `verbosity` | 0 | smolagents log level, 0–3 |
| `memory_policy` | `none` | episode mode; see below |
| `memory_compact_interval` | 0 | `interval` / `hybrid`: compact every N periods |
| `memory_compact_token_threshold` | 200000 | `hybrid`: compact when input tokens exceed this |

## Memory policies

Memory grows with every period, so long episodes eventually overflow the
context window. Compaction replaces it with an LM-written summary of what
worked.

| Policy | Compacts |
|---|---|
| `none` | never |
| `interval` | every `memory_compact_interval` periods |
| `agent_decides` | when the agent calls `request_memory_compaction` |
| `hybrid` | on any of the above, or when input tokens pass the threshold |

Each compaction is logged in `trace.jsonl` and its summary saved under
`<episode_dir>/compactions/`.
