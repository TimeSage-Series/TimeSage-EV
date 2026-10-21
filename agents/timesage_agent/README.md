# timesage_agent — skill-aware agent harness

Thin wrapper over [`smolagents_agent`](../smolagents_agent/) that adds a
**per-sweep skill library**: agents can save reusable Python functions
during one period and call them as live tools in subsequent periods.

## Two new tools

* **`induct_skill(name, description, code, inputs_schema, output_type, notes?, tags?)`**
  Saves the snippet to a markdown + python pair under the sweep's skill
  directory. The skill becomes available as a callable tool in the next
  period(s).
* **`retrieve_skill(name)`**
  Returns the markdown body (notes + code) of a saved skill, so the
  agent can decide whether to invoke it without committing.

Each saved skill is *also* indexed in the agent's system prompt under an
"Available skills" section (`(name, description)` pairs only — bodies are
pulled on demand via `retrieve_skill`).

## Storage layout

```
exp/<target>/skills/<llm-slug>/
├── <skill-name>.md      ← YAML frontmatter (metadata) + markdown body (notes + code)
└── <skill-name>.py      ← executable; defines top-level `def skill(...)`
```

The `.py` file is dynamically imported and wrapped in a smolagents `Tool`
subclass each time the worker starts a period.

Override with `TIMESAGE_SKILL_DIR=<path>` if you want a cross-sweep
library (default is per-sweep, isolated per-llm).

## Skill file format

Each `<name>.md` looks like:

```markdown
---
name: load_iso_week_row
description: Load timeseries.csv and return the row matching the given ISO week label.
tags: [pandas, csv, iso_week]
inputs_schema:
  iso_week:
    type: string
    description: ISO week label like '2025-W49'.
output_type: object
inducted_from:
  scenario: bls_diesel_retail_price_band_weekly
  period: 2025-W49
  llm_slug: qwen3-5-397b-a17b-nvfp4-tbc
  ts: 2026-05-22T14:05:00Z
---

## Notes

Assumes columns `iso_week` and `price_usd_per_gal`. Returns `{}` if no
match.

## Code

```python
def skill(iso_week: str) -> dict:
    import pandas as pd
    df = pd.read_csv('timeseries.csv')
    rows = df[df['iso_week'] == iso_week]
    return {} if rows.empty else rows.iloc[0].to_dict()
```
```

Description has a **hard 160-char cap**, soft 1-sentence guideline. The
prompt aggressively enforces this so future agents can scan the index
cheaply.

## Usage

Same as `smolagents_agent`, but with `--agent timesage_agent`:

```bash
uv pip install -e agents/timesage_agent/

evsandbox sweep --mode episode --agent timesage_agent \
  --agent-arg lm_provider=spike \
  --agent-arg lm_model=Gemma-4-31B-IT-NVFP4 \
  --judge spike --judge-model DeepSeek-V4-Flash \
  --target timesage-smoke
```

## Architecture notes

* `worker.py` mirrors `smolagents_agent.worker` almost verbatim — same
  stdin/stdout JSON contract, same stdout-fd-duping discipline, same
  episode-vs-single dispatch. The only adapters are (a) compute
  `skill_dir`, (b) inject `induct_skill` + `retrieve_skill` + all
  previously-saved skill-tools into `agent._agent.tools`, (c) prepend a
  skill-index block to the prompt before each `agent.run()`, (d) after
  each period, refresh the tool list if new skills were saved.
* Reuses `smolagents_agent.agent.TimeSageSmolAgent`,
  `smolagents_agent.lm.build_model`, and all three existing tools. No
  changes are required to the smolagents_agent package.
* No `evsandbox/runner.py` changes. The `evsandbox.cli` only needs a
  one-line addition to `AGENT_ALIASES` to wire `--agent timesage_agent`.

## Out of scope (v1)

* Cross-sweep skill aggregation (use `TIMESAGE_SKILL_DIR` env var if you
  need it manually).
* Embedding-based skill retrieval — current retrieval is LLM-as-router
  (Claude-Code-style): descriptions in the prompt, agent picks.
* Automatic / non-agent-triggered induction at period boundaries.
* Skill versioning / dedup. Re-inducting the same name overwrites.
