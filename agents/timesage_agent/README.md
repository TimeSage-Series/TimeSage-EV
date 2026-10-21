# timesage_agent

[`smolagents_agent`](../smolagents_agent/) plus a skill library: the agent can
save a Python function in one period and call it as a tool in later periods
of the same episode.

## Usage

Same `agent_args` as `smolagents_agent`; skills carry over only in episode
mode.

```bash
evsandbox sweep --mode episode --agent timesage_agent \
  --agent-arg lm_provider=anthropic --agent-arg lm_model=claude-sonnet-4-6 \
  --judge anthropic --target timesage-skills
```

## Tools

- `induct_skill(name, description, code, inputs_schema, output_type, notes?, tags?)`
  — saves a function `def skill(...)`; it becomes a tool from the next period.
- `retrieve_skill(name)` — returns a saved skill's notes and code.

Saved skills are listed by name and description (≤ 160 characters) at the top
of each period's prompt. Each skill is a markdown file with YAML front matter
plus a `.py` file, stored per model and scenario in
`exp/<target>/skills/<llm-slug>/<scenario_id>/`. Re-inducting a name
overwrites it.
