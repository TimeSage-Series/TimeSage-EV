# Tasks and the Engine

The engine — `evbench/engine/` — owns everything between a built instance and
what an agent sees. Each scenario's task contract lives in
`evbench/tasks/<tier>/<domain>/<scenario_id>/`:

```text
session_brief.md      # Task and # Input: role, input columns, reference
question_template.md  # Question: per-period questions with {{placeholders}},
                      each with its options and the rule that decides them
answer_schema.json    answer fields; copied into the sandbox
keypoints.yaml        scored keypoints (accuracy, coverage axes)
eval_rubric.yaml      report-quality rubric
scoring.yaml          pass threshold
question_tags.yaml    per-field question-type tags
```

An instance is `instances/<period>/{timeseries.csv, ground_truth.json,
gt_evidence.md, instance.json}` in the scenario corpus. `instance.json` holds
the values for the question template's placeholders (data month, release
month, ISO week, …), which only the scenario's own build scripts know.

For one `(scenario, period)` the engine loads the contract (`load_scenario`),
renders the question from `question_template.md` and the instance's
`instance.json` (`render_question`), applies the rephrase strategy and
assembles the prompt — `# Task`, `# Input`, `# Question`, then an
`# Answer Format` generated from `answer_schema.json` (`task_prompt`,
`episode_prompt`) — and builds the period-truncated sandbox (`build_world`).

```python
from pathlib import Path
from evbench.engine import load_scenario, task_prompt

scen_dir = Path("evbench/scenarios/easy/climate/noaa_cpc_ao_monthly_phase")
prompt, _ = task_prompt(load_scenario(scen_dir), scen_dir, "2024-05")
```
