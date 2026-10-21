"""Registry of self-hosted, OpenAI-compatible inference endpoints.

The experiments in the paper ran their open-weight models against a private
cluster. Those endpoints are not reachable outside that network and are not
baked into this release, so the registry starts empty and is populated from
your own configuration:

  * `TIMESAGE_MODELS_CONFIG=/path/to/models.yaml` — a mapping of model slug to
    base URL, either at the top level or under a `models:` key:

        models:
          my-qwen-70b: https://qwen.internal.example/v1
          my-llama-8b: https://llama.internal.example/v1

  * `SPIKE_BASE_URL=https://host/v1` — a single endpoint used for any model
    slug that the config does not name. Handy for one-off runs.

Auth comes from `SPIKE_API_KEY` (default `"EMPTY"`, which is what most
self-hosted vLLM/SGLang deployments expect).

The environment-variable names keep their original spelling so existing run
scripts and `.env` files keep working.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

__all__ = ["load_registry", "base_url_for", "api_key", "registry_help", "served_model_id"]

ENV_CONFIG = "TIMESAGE_MODELS_CONFIG"
ENV_FALLBACK_URL = "SPIKE_BASE_URL"
ENV_API_KEY = "SPIKE_API_KEY"


@lru_cache(maxsize=1)
def load_registry() -> dict[str, str]:
    """Return `{model_slug: base_url}` from the config file, or `{}`."""
    path = os.environ.get(ENV_CONFIG)
    if not path or not os.path.exists(path):
        return {}
    try:
        import yaml
    except ImportError:                                       # pragma: no cover
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
    except Exception:
        return {}
    if isinstance(doc, dict) and isinstance(doc.get("models"), dict):
        doc = doc["models"]
    if not isinstance(doc, dict):
        return {}
    return {str(k): str(v) for k, v in doc.items() if isinstance(v, str)}


def base_url_for(model: str) -> Optional[str]:
    """Base URL for `model`: the config entry, else `$SPIKE_BASE_URL`, else None."""
    hit = load_registry().get(model)
    if hit:
        return hit
    return os.environ.get(ENV_FALLBACK_URL) or None


def api_key() -> str:
    return os.environ.get(ENV_API_KEY, "EMPTY")


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


def registry_help(model: str) -> str:
    """A message that tells the user how to make `model` resolvable."""
    known = sorted(load_registry())
    if known:
        return (f"model {model!r} is not in {ENV_CONFIG}; "
                f"configured models: {known}")
    return (f"no self-hosted endpoint configured for model {model!r}. "
            f"Set {ENV_CONFIG} to a YAML file mapping model slugs to "
            f"OpenAI-compatible base URLs, or set {ENV_FALLBACK_URL} to a "
            f"single endpoint. See .env.example.")
