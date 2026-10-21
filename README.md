# TimeSage-EV

Benchmark core for TimeSage-EV: the code that builds and maintains the
scenarios, the engine that turns them into agent tasks, and the evaluator
that scores agent answers against them.

```text
TimeSage-EV/
├── agents/             # baseline agents (smolagents_agent, timesage_agent)
├── evbench/
│   ├── engine/         # task engine: contract → question, prompt, sandbox
│   ├── tasks/          # per-scenario task contracts the engine reads
│   ├── evaluator/      # four scoring axes, LLM judge, aggregation, fixtures
│   ├── maintainer/     # per-scenario data pipeline + corpus tools
│   └── scenarios/      # built scenarios — a separate repo, hosted on Hugging Face
├── evsandbox/          # runs agents in time-isolated sandboxes and scores them
└── experiments/        # experiment configs (agent, models, judge) for `evsandbox --config`
```

Only the easy tier (20 scenarios, 763 instances) is released so far.

## Install

Python ≥ 3.10. Packages are installed editable: the engine reads
`evbench/tasks/` and the runner reads `evbench/scenarios/` in place.

With [uv](https://docs.astral.sh/uv/) — the repo root is a uv workspace whose
members are `evsandbox` and the two agents, pinned by `uv.lock`:

```bash
uv sync                           # .venv with evbench, evsandbox and both agents
uv sync --group anthropic         # + LiteLLM, only for lm_provider=anthropic
uv sync --extra maintainer        # + the scenario data pipeline
uv run evsandbox run …            # or: source .venv/bin/activate
```

`uv run` re-syncs to the plain `uv sync` set before each command, dropping
`anthropic`/`maintainer` packages; pass the same `--group`/`--extra` to
`uv run` when you need them.

With pip:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                          # engine + evaluator (`eval-suite`)
pip install -e evsandbox                  # agent runner (`evsandbox`)
pip install -e agents/smolagents_agent    # baseline agent; likewise timesage_agent
pip install -e "agents/smolagents_agent[anthropic]"   # only for lm_provider=anthropic
pip install -e ".[maintainer]"            # only to rebuild scenario data
```

`--isolation bwrap` also needs [bubblewrap](https://github.com/containers/bubblewrap)
(`bwrap` on PATH) and unprivileged user namespaces; no root or Docker.

## Quick start: one agent evaluation

Commands below assume the venv is active; with uv, prefix them with `uv run`.

```bash
cp .env.example .env              # add the API key and, for self-hosted models, SPIKE_BASE_URL
set -a; source .env; set +a
cp experiments/example.yaml experiments/mine.yaml   # pick agent model + judge

evsandbox run evbench/scenarios/easy/climate/noaa_cpc_ao_monthly_phase 2024-05 \
    --config experiments/mine.yaml
```

The run lands in `exp/<target>/<lm_model>/easy/noaa_cpc_ao_monthly_phase/2024-05/`:
`run_record.json` (the agent's answer and report), `trace.jsonl` (every agent
step: code, tool calls, observations, token usage), `score_record.json` (the
four axes, aggregate, pass/fail, which judge), `meta.json` and `stderr.log`.
`exp/<target>/config.json` holds the settings the command ran with. Drop the
scenario and period and use `evsandbox sweep --config …` for a whole tier.

## Scenarios

`evbench/scenarios/` is not part of this repository. It is its own git
repository, published to Hugging Face; clone it into `evbench/scenarios/`.
Layout is `<tier>/<domain>/<scenario_id>/instances/<period>/`.

## Evaluator — `evbench/evaluator/`

The four scoring axes (keypoint accuracy, keypoint coverage, report
faithfulness, report quality), the LLM judge (6 backends plus an offline
mock), aggregation with cluster-bootstrap CIs, and reporting.

```bash
eval-suite sweep --mock-judge                         # score the fixtures offline
python -m unittest evbench.evaluator.tests.test_scorers
```

## Engine — `evbench/engine/`, `evbench/tasks/`

The engine owns everything between a built instance and what an agent sees.
Each scenario's task contract lives in `evbench/tasks/<tier>/<domain>/<scenario_id>/`:

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

For one `(scenario, period)` the engine loads the contract (`load_scenario`),
renders the question from `question_template.md` and the instance's
`instance.json` (`render_question`), applies the rephrase strategy and
assembles the prompt — `# Task`, `# Input`, `# Question`, then an
`# Answer Format` generated from `answer_schema.json` (`task_prompt`,
`episode_prompt`) — and builds the period-truncated sandbox (`build_world`).

```python
from evbench.engine import load_scenario, task_prompt
scen_dir = Path("evbench/scenarios/easy/climate/noaa_cpc_ao_monthly_phase")
prompt, _ = task_prompt(load_scenario(scen_dir), scen_dir, "2024-05")
```

## Maintainer — `evbench/maintainer/`

The maintainer updates the source data and creates instances; it does not
define the task. One directory per scenario, mirroring `evbench/scenarios/`:

```text
evbench/maintainer/<tier>/<domain>/<scenario_id>/
├── scenario.json      registry card
└── scripts/           download.py, format.py, template_vars.py, …
```

An instance is `instances/<period>/{timeseries.csv, ground_truth.json,
gt_evidence.md, instance.json}`. `instance.json` holds the values for the
question template's placeholders (data month, release month, ISO week, …),
which only the scenario's own scripts know.

`pipeline/` drives the build across scenarios. Downloads land in a working
tree (`scenarios_hf/` by default, or `$TIMESAGE_DATA_ROOT`), are compared
against the released corpus, and only then published into `evbench/scenarios/`:

```bash
evbench/maintainer/pipeline/download_all.sh -t easy
evbench/maintainer/pipeline/format_all.sh -t easy --with-ground-truth
python evbench/maintainer/pipeline/compare_reference.py -t easy
python evbench/maintainer/pipeline/publish_periods.py -t easy --dry-run
python evbench/maintainer/corpus/validate_scenarios.py --all
```

See [`evbench/maintainer/README.md`](evbench/maintainer/README.md).

## Sandbox and agents — `evsandbox/`, `agents/`

`evsandbox` materialises each instance into an isolated working directory
(no data past the cutoff), spawns the agent as a subprocess over a JSON-stdio
contract, audits its network access, and scores the answer with
`evbench.evaluator`. Runs land in `exp/<target>/<llm>/<tier>/<scenario>/<period>/`.

```bash
evsandbox run evbench/scenarios/easy/climate/noaa_cpc_ao_monthly_phase 2024-05 \
    --agent smolagents_agent --agent-arg lm_provider=anthropic --agent-arg lm_model=claude-sonnet-4-6
evsandbox sweep --tier easy --agent smolagents_agent \
    --agent-arg lm_provider=anthropic --agent-arg lm_model=claude-sonnet-4-6
evsandbox sweep --tier easy --agent smolagents_agent --isolation bwrap \
    --agent-arg lm_provider=anthropic --agent-arg lm_model=claude-sonnet-4-6   # agent can't see the data trees
evsandbox sweep --config experiments/example.yaml        # the same, pinned in an experiment file
evsandbox searxng up                                   # local web search, if a scenario uses it
```

By default the agent is a plain subprocess whose cwd is the sandbox; it can
still read the rest of the host, ground truth included. `--isolation bwrap`
runs it under [bubblewrap](https://github.com/containers/bubblewrap) instead —
no root or daemon needed — where it sees only the sandbox (at `/root`), its
run's output dir (at `/out`), the Python environment and the code it imports
(see [`evsandbox/evsandbox/isolation.py`](evsandbox/evsandbox/isolation.py)).

The agent contract is in [`agents/README.md`](agents/README.md).

## Configuration

Copy `.env.example` to `.env`, fill in only what you use, and load it into
the shell (`set -a; source .env; set +a`) — no code reads `.env` itself.
Self-hosted open-weight models, for both the judge and agents, are configured
through `TIMESAGE_MODELS_CONFIG` (a YAML map of model name to OpenAI-compatible
base URL) or a single `SPIKE_BASE_URL`; see
[`evbench/evaluator/model_registry.py`](evbench/evaluator/model_registry.py).
Which models an experiment uses — the agent's `lm_provider`/`lm_model` and the
judge's backend and models — is not environment: it goes in an experiment
config passed with `--config` (start from
[`experiments/example.yaml`](experiments/example.yaml); command-line flags
override it). Each command writes the settings it actually ran with to
`exp/<target>/config.json`, and every `score_record.json` names its judge.

The runner forwards the API keys, these two settings and proxy variables to the
agent; under `--isolation bwrap` it also mounts the `TIMESAGE_MODELS_CONFIG`
file and the host's DNS resolver config.
