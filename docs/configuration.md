# Configuration

Two places hold settings: the environment for secrets and endpoints, and an
experiment config for everything that decides a result.

## Environment — `.env`

Copy `.env.example` to `.env`, fill in only what you use, and load it into
the shell (`set -a; source .env; set +a`) — no code reads `.env` itself.

Self-hosted open-weight models, for both the judge and agents, use one
OpenAI-compatible endpoint, `SELF_HOSTED_BASE_URL` (key `SELF_HOSTED_API_KEY`);
an experiment config can point the agent or the judge elsewhere. See
[`evbench/evaluator/self_hosted.py`](../evbench/evaluator/self_hosted.py).

The runner forwards the API keys, these two settings and proxy variables to the
agent; under `--isolation bwrap` it also mounts the host's DNS resolver
config.

## Experiment config — `--config`

Which models an experiment uses — the agent's `lm_provider`/`lm_model` and the
judge's backend and models — is not environment: it goes in an experiment
config passed with `--config` (start from
[`experiments/example.yaml`](../experiments/example.yaml); command-line flags
override it). Each command writes the settings it actually ran with to
`exp/<target>/config.json`, and every `score_record.json` names its judge.

## Run outputs

A run lands in `exp/<target>/<lm_model>/<tier>/<scenario>/<period>/`:

| File | Contents |
|---|---|
| `run_record.json` | the agent's answer and report |
| `trace.jsonl` | every agent step: code, tool calls, observations, token usage |
| `score_record.json` | the four axes, aggregate, pass/fail, which judge |
| `meta.json`, `stderr.log` | run metadata and the agent's stderr |
