"""Model factory for the smolagents-based TimeSage agent.

Routing rules:
  * lm_provider="self_hosted"
        → OpenAIServerModel pointed at agent_args.lm_base_url (or env
          SELF_HOSTED_BASE_URL), with the served model name auto-resolved
          via /v1/models.
  * lm_provider="openai"
        → OpenAIServerModel against api.openai.com (uses OPENAI_API_KEY).
  * lm_provider="anthropic"
        → LiteLLMModel("anthropic/<model>"); requires litellm + anthropic.
        Auto-injects ephemeral cache_control on system + last message
        (Anthropic prompt caching, ~10× cheaper on cached prefix).
        Disable via agent_args.prompt_cache=False.
  * lm_provider="openrouter"
        → OpenAIServerModel pointed at openrouter.ai. lm_model carries
          the provider prefix (e.g., "anthropic/claude-sonnet-4-6",
          "openai/gpt-5.4"). For anthropic/* targets, cache_control is
          injected and forwarded — OpenRouter returns the Anthropic
          cache discount. OpenAI/* targets get OpenAI's server-side
          automatic caching transparently (no client opt-in needed).

Token usage is harvested by the smolagents framework (per-step on
ChatMessage.token_usage; aggregate on RunResult.token_usage), so we
don't override anything here.
"""
from __future__ import annotations

import os
from typing import Any


from evbench.evaluator.self_hosted import (  # noqa: E402
    api_key as _self_hosted_api_key, base_url as _self_hosted_base_url,
    served_model_id as _served_model_id,
)


def _resolve_served_model_id(base_url: str, api_key: str,
                             requested: str | None = None) -> str:
    """Hit GET /v1/models and pick the id to send (see served_model_id):
    `requested` when the endpoint lists it, else the only model a
    single-model pod serves.

    vLLM's --served-model-name often differs from the URL slug, so we
    cannot guess it.
    """
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=api_key or "EMPTY",
                    timeout=600.0, max_retries=2)
    listed = client.models.list()
    data = getattr(listed, "data", None) or []
    return _served_model_id([m.id for m in data], requested)


def _mark_last_block_with_cache(msg: dict) -> None:
    """Convert string content to list-of-blocks form and set ephemeral
    cache_control on the last block. Anthropic requires cache_control on
    a content block, not the message dict itself."""
    content = msg.get("content")
    mark = {"type": "ephemeral"}
    if isinstance(content, str):
        msg["content"] = [{"type": "text", "text": content,
                           "cache_control": mark}]
    elif isinstance(content, list) and content:
        last = dict(content[-1])
        last["cache_control"] = mark
        msg["content"] = content[:-1] + [last]


def _inject_anthropic_cache_markers(messages: list[dict]) -> list[dict]:
    """Mark system message + last message with cache_control.

    Anthropic's rolling-cache pattern: each turn marks the current end,
    next turn matches the cached prefix. With 2 markers we stay well
    inside the 4-breakpoint limit and capture the stable prefix
    (system + task + prior steps) which is ~80%+ of input tokens in
    agentic multi-step loops.
    """
    if not messages:
        return messages
    out = [dict(m) for m in messages]
    for m in out:
        if m.get("role") == "system":
            _mark_last_block_with_cache(m)
            break
    _mark_last_block_with_cache(out[-1])
    return out


def _with_anthropic_caching(base_cls):
    """Return a subclass of `base_cls` (any ApiModel) that injects
    Anthropic cache_control markers on the prepared messages.

    Works for both LiteLLMModel (direct Anthropic API) and OpenAIServerModel
    (OpenRouter routing anthropic/* models — OpenRouter passes cache_control
    through to Anthropic and returns the discount).
    """
    class Wrapped(base_cls):
        def _prepare_completion_kwargs(self, *args, **kwargs):
            ck = super()._prepare_completion_kwargs(*args, **kwargs)
            ck["messages"] = _inject_anthropic_cache_markers(ck["messages"])
            return ck

    Wrapped.__name__ = f"{base_cls.__name__}WithAnthropicCache"
    return Wrapped


def build_model(lm_model: str, agent_args: dict) -> Any:
    """Return a smolagents Model instance configured per agent_args."""
    from smolagents import OpenAIServerModel

    provider = (agent_args.get("lm_provider") or "").lower()
    max_tokens = int(agent_args.get("max_tokens") or 8192)
    temperature = float(agent_args.get("temperature") or 0.0)
    timeout = float(agent_args.get("timeout") or 600.0)

    if provider == "self_hosted":
        base_url = _self_hosted_base_url(agent_args.get("lm_base_url"))
        api_key = _self_hosted_api_key(agent_args.get("lm_api_key"))
        served = _resolve_served_model_id(base_url, api_key, lm_model or None)
        return OpenAIServerModel(
            model_id=served,
            api_base=base_url,
            api_key=api_key,
            client_kwargs={"timeout": timeout, "max_retries": 2},
            max_tokens=max_tokens,
            temperature=temperature,
        )

    if provider == "openai":
        return OpenAIServerModel(
            model_id=lm_model,
            api_key=os.environ.get("OPENAI_API_KEY"),
            max_tokens=max_tokens,
            temperature=temperature,
        )

    if provider == "anthropic":
        from smolagents import LiteLLMModel
        model_id = lm_model if lm_model.startswith("anthropic/") \
                   else f"anthropic/{lm_model}"
        prompt_cache = bool(agent_args.get("prompt_cache", True))
        cls = _with_anthropic_caching(LiteLLMModel) if prompt_cache else LiteLLMModel
        return cls(model_id=model_id,
                   api_key=os.environ.get("ANTHROPIC_API_KEY"),
                   max_tokens=max_tokens,
                   temperature=temperature)

    if provider == "openrouter":
        # OpenRouter is OpenAI-compatible. Model id includes provider
        # prefix (e.g. "anthropic/claude-sonnet-4-6", "openai/gpt-5.4").
        # For anthropic/* targets we inject cache_control on messages —
        # OpenRouter forwards it to Anthropic and returns the discount
        # (10× cheaper input on cached prefix).
        base_url = (agent_args.get("lm_base_url")
                    or os.environ.get("OPENROUTER_BASE_URL")
                    or "https://openrouter.ai/api/v1")
        api_key = (agent_args.get("lm_api_key")
                   or os.environ.get("OPENROUTER_API_KEY"))
        if not api_key:
            raise RuntimeError(
                "lm_provider=openrouter requires OPENROUTER_API_KEY "
                "(or agent_args.lm_api_key)"
            )
        prompt_cache = bool(agent_args.get("prompt_cache", True))
        is_anthropic = lm_model.startswith("anthropic/")
        base = OpenAIServerModel
        if is_anthropic and prompt_cache:
            base = _with_anthropic_caching(OpenAIServerModel)
        # OpenRouter→Anthropic with cache_control is prone to CLOSE_WAIT
        # half-closed sockets when OpenRouter's upstream times out on slow
        # Sonnet responses. A single-value httpx timeout (the SDK default)
        # leaves the read hanging for the full budget. Use granular
        # httpx.Timeout so CLOSE_WAIT trips the read deadline in 180s
        # and max_retries=2 kicks in, rather than blocking ~10 minutes.
        if is_anthropic:
            import httpx
            sdk_timeout = httpx.Timeout(
                connect=30.0, read=180.0, write=30.0, pool=None
            )
        else:
            sdk_timeout = timeout
        return base(
            model_id=lm_model,
            api_base=base_url,
            api_key=api_key,
            client_kwargs={"timeout": sdk_timeout, "max_retries": 2},
            max_tokens=max_tokens,
            temperature=temperature,
        )

    raise RuntimeError(
        f"unknown lm_provider={provider!r}; supported: "
        f"self_hosted, openai, anthropic, openrouter"
    )
