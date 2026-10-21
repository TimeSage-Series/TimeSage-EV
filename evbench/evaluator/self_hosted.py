"""Self-hosted, OpenAI-compatible inference endpoints (vLLM, SGLang, ...).

The experiments in the paper ran their open-weight models on a private
cluster that is not reachable from outside, so no endpoint ships with this
release. Point it at your own:

  * `SELF_HOSTED_BASE_URL=https://host/v1` — the endpoint, for the agent and
    the judge alike. A gateway serving several models is one endpoint: the
    model is chosen per request.
  * `SELF_HOSTED_API_KEY` — default `"EMPTY"`, which is what most vLLM/SGLang
    deployments expect.

When the agent and the judge run on different hosts, an experiment config
overrides the URL for either one: `agent.args.lm_base_url`, `judge.base_url`.
"""
from __future__ import annotations

import os
from typing import Optional

__all__ = ["base_url", "api_key", "served_model_id"]

ENV_BASE_URL = "SELF_HOSTED_BASE_URL"
ENV_API_KEY = "SELF_HOSTED_API_KEY"


def base_url(override: Optional[str] = None) -> str:
    """`override` if given, else `$SELF_HOSTED_BASE_URL`."""
    url = override or os.environ.get(ENV_BASE_URL)
    if not url:
        raise RuntimeError(
            f"no self-hosted endpoint configured: set {ENV_BASE_URL} to an "
            f"OpenAI-compatible base URL (see .env.example), or set base_url "
            f"in the experiment config.")
    return url


def api_key(override: Optional[str] = None) -> str:
    return override or os.environ.get(ENV_API_KEY) or "EMPTY"


def served_model_id(listed: list[str], requested: Optional[str]) -> str:
    """Pick the model id to send, given an endpoint's /v1/models listing.

    A gateway serves several models, so the requested one must be among
    them. A single-model vLLM pod may report its own name (often a HF repo
    path) instead of the slug it was configured under; then the one listed
    id is used. Never falls back to some other model of a multi-model
    endpoint.
    """
    if requested and requested in listed:
        return requested
    if len(listed) == 1:
        return listed[0]
    if not listed:
        raise RuntimeError("endpoint reports no models at /v1/models")
    raise RuntimeError(f"endpoint serves {listed}; requested model "
                       f"{requested!r} is not among them")
