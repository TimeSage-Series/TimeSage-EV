# Installation

Python ≥ 3.10. Packages are installed editable: the engine reads
`evbench/tasks/` and the runner reads `evbench/scenarios/` in place.

## With uv

The repo root is a [uv](https://docs.astral.sh/uv/) workspace whose members are
`evsandbox` and the two agents, pinned by `uv.lock`:

```bash
uv sync                           # .venv with evbench, evsandbox and both agents
uv sync --group anthropic         # + LiteLLM, only for lm_provider=anthropic
uv sync --extra maintainer        # + the scenario data pipeline
uv run evsandbox run …            # or: source .venv/bin/activate
```

`uv run` re-syncs to the plain `uv sync` set before each command, dropping
`anthropic`/`maintainer` packages; pass the same `--group`/`--extra` to
`uv run` when you need them.

## With pip

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                          # engine + evaluator (`eval-suite`)
pip install -e evsandbox                  # agent runner (`evsandbox`)
pip install -e agents/smolagents_agent    # baseline agent; likewise timesage_agent
pip install -e "agents/smolagents_agent[anthropic]"   # only for lm_provider=anthropic
pip install -e ".[maintainer]"            # only to rebuild scenario data
```

## The scenario corpus

`evbench/scenarios/` is not part of this repository. It is its own git
repository, published to Hugging Face; clone it into `evbench/scenarios/`.
Layout is `<tier>/<domain>/<scenario_id>/instances/<period>/`.

The source reports behind it (PDF/XLS, 2.3 GB) are restored separately, and
only when an agent should read them inside the sandbox or a scenario is
rebuilt — see [`evbench/maintainer/README.md`](../evbench/maintainer/README.md).

## Sandbox isolation (optional)

`--isolation bwrap` also needs [bubblewrap](https://github.com/containers/bubblewrap)
(`bwrap` on PATH) and unprivileged user namespaces; no root or Docker.
