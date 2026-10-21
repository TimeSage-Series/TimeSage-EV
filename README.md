# TimeSage-EV

**TimeSage-EV** measures how well agents analyze periodically released time series data, a defining challenge for agents that operate over long horizons and are expected to improve continuously.

## Quickstart

TimeSage-EV requires Python 3.10 or later and [uv](https://docs.astral.sh/uv/);
[bubblewrap](https://github.com/containers/bubblewrap) is optional, for
sandboxing the agent.

```bash
git clone https://github.com/TimeSage-Series/TimeSage-EV && cd TimeSage-EV
uv sync && source .venv/bin/activate
git clone https://huggingface.co/datasets/TimeSage-Series/TimeSage-EV evbench/scenarios
```

Add the model provider keys you need to a `.env` file in the project root
(start from `.env.example`) and load it, then verify the CLI and run one
scenario:

```bash
cp .env.example .env && set -a && source .env && set +a
evsandbox --help
cp experiments/example.yaml experiments/mine.yaml   # pick the agent model and the judge
evsandbox run evbench/scenarios/easy/climate/noaa_cpc_ao_monthly_phase 2024-05 \
    --config experiments/mine.yaml
```

The run lands in `exp/<target>/<lm_model>/easy/noaa_cpc_ao_monthly_phase/2024-05/`
with the agent's answer, its full trace and the score. Drop the scenario and
period and use `evsandbox sweep --config …` for a whole tier.

## Further Documentation

- [Installation](docs/installation.md) — uv and pip setups, optional extras, the scenario corpus, bubblewrap
- [Configuration](docs/configuration.md) — API keys, self-hosted models, experiment configs, run outputs
- [Tasks and the Engine](docs/tasks.md) — The task contract and how a prompt and sandbox are built
- [Agent Contract](agents/README.md) — The JSON-stdio protocol an agent implements
- [Example Experiment](experiments/example.yaml) — Every experiment setting, annotated
- [Maintainer Guide](evbench/maintainer/README.md) — Refreshing source data and validating the corpus

## Core Components

### Scenarios and Tasks

A scenario follows one public data series through consecutive releases; each
release period is an instance, so an agent that carries what it learned from
earlier periods should do better than one that starts over every time. Each scenario has:

- per-period instances: the series truncated to the period, the ground
  truth and the evidence that grounds it
- a task contract: role, questions, answer schema, scored keypoints and a
  report rubric
- a pass threshold for repeatable comparisons across agents.

### Agents

Agents are the systems evaluated by the benchmark. They run as subprocesses
over a JSON-stdio contract, so any language or framework works. Two baselines
live in `agents/`:

- [`smolagents_agent`](agents/smolagents_agent/README.md) — a smolagents
  CodeAgent with memory that accumulates across periods,
- [`timesage_agent`](agents/timesage_agent/README.md) — the same, plus a skill
  library: functions saved in one period become tools in the next.

Both work with Anthropic, OpenAI, OpenRouter or a self-hosted
OpenAI-compatible endpoint.

### Execution Environment

`evsandbox` builds each period's sandbox with no data past the cutoff, spawns
the agent, records its trace, audits its network access and scores the
answer. It runs periods independently or as an episode with feedback between
them, and with `--isolation bwrap` the agent sees only its sandbox, its
output directory and the code it imports. After installing, explore the
options with:

```bash
evsandbox run --help
evsandbox sweep --help
evsandbox episode --help
```

### Evaluator

`evbench/evaluator/` scores each answer on four axes — keypoint accuracy,
keypoint coverage, report faithfulness and report quality — with an LLM judge
(five backends, including self-hosted models, plus an offline mock), and
aggregates results with cluster-bootstrap confidence intervals.

### Data Pipeline

`evbench/maintainer/` holds each scenario's download and build scripts. It
refreshes the source data, extends the corpus to new periods without touching
the released ones, and validates the result for structure and leakage.

## Contribution

- [Adding an Agent](agents/README.md) — Implement the contract and run it with `--agent-cmd`
- [Adding or Refreshing a Scenario](evbench/maintainer/README.md) — Build scripts, pipeline and validation

Contributions are welcome, especially agents that learn across periods and
new scenarios built on public data series.
