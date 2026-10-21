"""LLM-judge backend with caching.

Backends:
  * "anthropic"        — Anthropic API (default). claude-haiku for cheap
                         axes, claude-sonnet for Quality.
  * "claude_thinking"  — Anthropic API with extended thinking enabled.
                         Functionally equivalent to running Claude Code CLI
                         in `thinking=middle` mode (same models, same
                         thinking machinery); no `claude` binary needed.
  * "claude_cli"       — Shells out to the `claude` binary in non-interactive
                         mode (`claude -p`). Uses Claude Code's OAuth login
                         when ANTHROPIC_API_KEY isn't set. Maps tier to
                         `--effort low|medium|high`.
  * "openrouter"       — OpenAI-compatible client pointed at openrouter.ai.
                         Routes to any model on OpenRouter (e.g.,
                         `openai/gpt-5.4`).
  * "spike"            — OpenAI-compatible client pointed at the SPIKE
                         institutional inference endpoint. `model` must be a
                         slug configured in TIMESAGE_MODELS_CONFIG (see .env.example).
                         Zero marginal cost; auto-resolves the vLLM served
                         model id from /v1/models on the first call.
  * "mock"             — Deterministic stubs (no API). Legacy `mock=True`
                         still works.

All calls (except mock) cached by sha256(backend + model + prompt + ref)
at `~/.cache/timesage_eval/judge_cache/`.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# Convention for the `thinking` knob exposed by the CLI:
#   low    →  2048 tokens   (SDK)  ↔  --effort low     (CLI)
#   middle → 10000 tokens   (SDK)  ↔  --effort medium  (CLI)
#   high   → 20000 tokens   (SDK)  ↔  --effort high    (CLI)
# Anthropic SDK enforces budget_tokens >= 1024.
THINKING_BUDGETS = {"low": 2048, "middle": 10000, "high": 20000}
CLI_EFFORT_TIERS = {"low": "low", "middle": "medium", "high": "high"}


CACHE_DIR = Path(os.environ.get("TIMESAGE_EVAL_CACHE")     # empty counts as unset
                 or os.path.expanduser("~/.cache/timesage_eval/judge_cache"))


# Self-hosted, OpenAI-compatible endpoints for open-weight judges.
# Populated from your own config — see evbench/evaluator/model_registry.py
# and .env.example. Empty by default: the release ships no private endpoints.
from .model_registry import (  # noqa: E402
    api_key as _self_hosted_api_key, base_url_for as _self_hosted_base_url,
    registry_help as _self_hosted_help, served_model_id as _served_model_id,
)


#: Response budget for a judge call unless the experiment config sets one.
DEFAULT_MAX_TOKENS = 2048
#: The judge calls the scorers make, by `kind`; `by_kind` options key on these.
JUDGE_KINDS = ("coverage", "decompose", "verify", "quality")
#: Request options `by_kind` may set for one kind; each replaces the
#: judge-wide value.
KIND_OPTIONS = ("max_tokens", "extra_body")


class JudgeUnavailable(RuntimeError):
    """The judge returned nothing usable: an empty or truncated answer."""


def _check_answer(text: str, truncated: bool) -> str:
    """Reject replies a scorer would silently read as "no" / zero.

    A reasoning model can spend the whole token budget thinking and return
    empty content with finish_reason=length.
    """
    if truncated:
        raise JudgeUnavailable("reply truncated at max_tokens "
                               "(raise judge.max_tokens or turn reasoning off)")
    if not text.strip():
        raise JudgeUnavailable("empty reply")
    return text


@dataclass
class JudgeResult:
    text: str
    parsed: Any = None
    cost_usd: float = 0.0
    cached: bool = False
    status: str = "ok"          # ok | error | cached


@dataclass
class Judge:
    """Pluggable judge.

    Backends are selected via `backend`:
      * "anthropic"       — direct Anthropic SDK call (default).
      * "claude_thinking" — Anthropic SDK with extended thinking enabled
                            (`thinking_budget` tokens). Same models as
                            "anthropic"; mimics Claude Code's thinking mode.
      * "openrouter"      — OpenAI-compatible client against
                            `openrouter.ai/api/v1`. `model` and
                            `quality_model` should be OpenRouter slugs
                            (e.g., "openai/gpt-5.4").
      * "mock"            — Deterministic stubs. Legacy `mock=True`
                            mapped here for compatibility.
    """
    model: str = "claude-haiku-4-5-20251001"
    quality_model: str = "claude-sonnet-4-6"
    mock: bool = False
    backend: str = "anthropic"
    thinking_budget: int = 10000          # claude_thinking backend
    thinking_tier: str = "middle"         # claude_cli backend (low|middle|high)
    cli_path: Optional[str] = None        # auto-discovered if None
    cli_timeout_s: int = 300
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    max_tokens: int = DEFAULT_MAX_TOKENS
    # Extra request-body fields for OpenAI-compatible backends (spike,
    # openrouter), e.g. {"chat_template_kwargs": {"thinking": False}}.
    extra_body: dict[str, Any] = field(default_factory=dict)
    # Per-kind request options replacing max_tokens / extra_body for that kind,
    # e.g. {"verify": {"extra_body": {"reasoning_effort": "low"}}} to let only
    # the fact-checking call reason (it must recompute derived numbers).
    by_kind: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Calls that returned nothing usable after a retry, per thread (a sweep
    # shares one Judge across worker threads); see take_failures().
    _failures: threading.local = field(default_factory=threading.local,
                                       repr=False, compare=False)
    mock_responses: dict[str, str] = field(default_factory=dict)
    total_cost_usd: float = 0.0

    def describe(self) -> dict[str, Any]:
        """Which judge this is, for score records and experiment configs."""
        if self.backend == "mock":
            return {"backend": "mock"}
        out: dict[str, Any] = {"backend": self.backend, "model": self.model,
                               "quality_model": self.quality_model}
        if self.backend == "claude_thinking":
            out["thinking_budget"] = self.thinking_budget
        if self.backend == "claude_cli":
            out["thinking_tier"] = self.thinking_tier
        if self.max_tokens != DEFAULT_MAX_TOKENS:
            out["max_tokens"] = self.max_tokens
        if self.extra_body:
            out["extra_body"] = self.extra_body
        if self.by_kind:
            out["by_kind"] = self.by_kind
        return out

    def __post_init__(self):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._client = None
        # Legacy alias.
        if self.mock:
            self.backend = "mock"
        # OpenRouter defaults.
        if self.backend == "openrouter":
            self.api_base = self.api_base or "https://openrouter.ai/api/v1"
            self.api_key = self.api_key or os.environ.get("OPENROUTER_API_KEY")
        # SPIKE: one endpoint per model. We hold the base URL per-model and
        # build the OpenAI-compatible client lazily inside _call_spike — both
        # model and quality_model may point to different SPIKE pods.
        if self.backend == "spike":
            self.api_key = self.api_key or _self_hosted_api_key()
            for m in (self.model, self.quality_model):
                if _self_hosted_base_url(m) is None:
                    raise RuntimeError(f"spike backend: {_self_hosted_help(m)}")
            # Per-model lazily-cached client + resolved served-model id.
            self._spike_clients: dict[str, Any] = {}
            self._spike_served_id: dict[str, str] = {}
        # Claude CLI defaults.
        if self.backend == "claude_cli":
            if self.cli_path is None:
                self.cli_path = shutil.which("claude")
            if not self.cli_path:
                raise RuntimeError(
                    "claude_cli backend: `claude` binary not found on PATH. "
                    "Install with `npm i -g @anthropic-ai/claude-code`."
                )
            # Use plain aliases by default — CLI accepts 'sonnet' / 'opus'
            # to pick the latest model in each line.
            if self.model.startswith("claude-haiku"):
                self.model = "sonnet"
            if self.quality_model.startswith("claude-sonnet"):
                self.quality_model = "sonnet"

    # --------------- caching ---------------

    def _options(self, kind: str) -> tuple[int, dict[str, Any]]:
        """(max_tokens, extra_body) for a call of this kind."""
        over = self.by_kind.get(kind) or {}
        return (int(over.get("max_tokens", self.max_tokens)),
                dict(over.get("extra_body", self.extra_body)))

    def _key(self, prompt: str, reference: str, model: str,
             max_tokens: int = DEFAULT_MAX_TOKENS,
             extra_body: Optional[dict] = None) -> str:
        """Cache key includes backend+model so two judges don't collide, and
        the request options when set, so a reply produced with reasoning on
        is not reused with it off. Default options keep the original key."""
        opts = ""
        if max_tokens != DEFAULT_MAX_TOKENS or extra_body:
            opts = "\n---opts---\n" + json.dumps(
                {"max_tokens": max_tokens, "extra_body": extra_body or {}},
                sort_keys=True)
        return hashlib.sha256(
            (f"{self.backend}\n{model}\n{prompt}\n---ref---\n{reference}{opts}")
            .encode("utf-8")
        ).hexdigest()

    def _load_cache(self, key: str) -> Optional[str]:
        p = CACHE_DIR / f"{key}.json"
        if p.exists():
            try:
                text = json.loads(p.read_text())["text"]
            except Exception:
                return None
            # Empty replies were cached before _check_answer existed; they
            # are failures, not answers.
            return text if text.strip() else None
        return None

    def _save_cache(self, key: str, text: str) -> None:
        p = CACHE_DIR / f"{key}.json"
        p.write_text(json.dumps({"text": text}))

    def _pick_model(self, kind: str) -> str:
        return self.quality_model if kind == "quality" else self.model

    # --------------- core API ---------------

    def judge(self, prompt: str, reference: str = "",
              kind: str = "default") -> JudgeResult:
        """Run a single judge call. `kind` selects the model: 'quality' uses
        `quality_model`, anything else uses `model`."""
        if self.backend == "mock":
            # Mock mode bypasses the disk cache — each test sets its own
            # mock_responses, and the cache would otherwise cross-contaminate.
            return JudgeResult(text=self._mock_response(prompt, kind), status="ok")
        model = self._pick_model(kind)
        max_tokens, extra_body = self._options(kind)
        key = self._key(prompt, reference, model, max_tokens, extra_body)
        cached = self._load_cache(key)
        if cached is not None:
            return JudgeResult(text=cached, cached=True, status="cached")
        calls = {
            "anthropic":       lambda: self._call_anthropic(prompt, model, max_tokens,
                                                            with_thinking=False),
            "claude_thinking": lambda: self._call_anthropic(prompt, model, max_tokens,
                                                            with_thinking=True),
            "claude_cli":      lambda: self._call_claude_cli(prompt, model),
            "openrouter":      lambda: self._call_openrouter(prompt, model, max_tokens, extra_body),
            "spike":           lambda: self._call_spike(prompt, model, max_tokens, extra_body),
        }
        if self.backend not in calls:
            return JudgeResult(text="",
                               status=f"error: unknown backend {self.backend!r}")
        last: Exception = RuntimeError("no attempt made")
        for _ in range(2):          # one retry: empty/truncated replies vary run to run
            try:
                text, cost = calls[self.backend]()
                self.total_cost_usd += cost
                self._save_cache(key, text)
                return JudgeResult(text=text, status="ok", cost_usd=cost)
            except Exception as exc:                                   # noqa: BLE001
                last = exc
        msg = f"{kind} ({model}): {type(last).__name__}: {last}"[:300]
        self._thread_failures().append(msg)
        return JudgeResult(text="", status=f"error: {msg}")

    def _thread_failures(self) -> list[str]:
        if not hasattr(self._failures, "items"):
            self._failures.items = []
        return self._failures.items

    def take_failures(self) -> list[str]:
        """This thread's failed calls since the last take, then forget them.

        Scorers read an empty reply as "no" / zero, so their caller checks
        this after each axis and marks the axis judge_unavailable instead.
        """
        out = self._thread_failures()[:]
        self._thread_failures().clear()
        return out

    # --------------- backend implementations ---------------

    def _call_anthropic(self, prompt: str, model: str, max_tokens: int, *,
                         with_thinking: bool) -> tuple[str, float]:
        from anthropic import Anthropic
        if self._client is None:
            self._client = Anthropic()
        kwargs: dict[str, Any] = {
            "model":       model,
            "max_tokens":  max_tokens,
            "messages":    [{"role": "user", "content": prompt}],
        }
        if with_thinking:
            # Extended thinking requires temperature=1 and max_tokens > budget.
            budget = max(1024, int(self.thinking_budget))
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            kwargs["temperature"] = 1.0
            kwargs["max_tokens"] = budget + max_tokens
        else:
            kwargs["temperature"] = 0.0
        resp = self._client.messages.create(**kwargs)
        # The text response is in the LAST text block; thinking blocks come
        # earlier and aren't part of the answer.
        text = "".join(block.text for block in resp.content
                       if hasattr(block, "text"))
        _check_answer(text, resp.stop_reason == "max_tokens")
        # Rough cost — cache makes the actual spend bounded.
        return text, 0.001

    def _call_claude_cli(self, prompt: str, model: str) -> tuple[str, float]:
        """Shell out to `claude -p ... --output-format json`. Prompt goes via
        stdin to avoid argv length / shell-escaping issues.

        Returns (text, cost_usd). Cost is read from the CLI's own response
        (`.total_cost_usd`), which is the authoritative figure.
        """
        effort = CLI_EFFORT_TIERS.get(self.thinking_tier, "medium")
        cmd = [
            self.cli_path, "-p",
            "--model", model,
            "--effort", effort,
            "--output-format", "json",
            "--no-session-persistence",   # don't litter the user's session list
        ]
        # If ANTHROPIC_API_KEY is set in the env, prefer --bare so we skip
        # the ~18K-token Claude Code system prompt overhead.
        if os.environ.get("ANTHROPIC_API_KEY"):
            cmd.append("--bare")
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                timeout=self.cli_timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"claude CLI timed out after {self.cli_timeout_s}s") from exc
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI exit {proc.returncode}: "
                f"{(proc.stderr or proc.stdout or '').strip()[:500]}"
            )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"claude CLI returned non-JSON: {proc.stdout[:500]!r}") from exc
        if data.get("is_error") or data.get("subtype") != "success":
            raise RuntimeError(
                f"claude CLI reported error: {data.get('result')!r} "
                f"(status={data.get('api_error_status')})"
            )
        text = _check_answer(data.get("result") or "", truncated=False)
        cost = float(data.get("total_cost_usd") or 0.0)
        return text, cost

    def _call_spike(self, prompt: str, model: str, max_tokens: int,
                    extra_body: dict) -> tuple[str, float]:
        """OpenAI-compatible call against a self-hosted endpoint.

        The endpoint is either a single-model pod or a gateway in front of
        several. The request's `model` field is the *served* model id, picked
        from /v1/models on the first call (model_registry.served_model_id)
        and cached. Cost is recorded as 0 for self-hosted GPUs."""
        from openai import OpenAI
        client = self._spike_clients.get(model)
        if client is None:
            base = _self_hosted_base_url(model)
            client = OpenAI(base_url=base, api_key=self.api_key or "EMPTY",
                            timeout=120.0, max_retries=2)
            self._spike_clients[model] = client
            # Resolve served-model id (vLLM-internal name, may differ from
            # the URL slug — the server may report a HF repo path).
            try:
                ids = [m.id for m in client.models.list().data]
            except Exception as exc:                                    # noqa: BLE001
                raise RuntimeError(
                    f"SPIKE {model}: /v1/models failed ({exc}); pod may be "
                    f"swapped out — warm with spike_probe.py warm {model}"
                ) from exc
            try:
                self._spike_served_id[model] = _served_model_id(ids, model)
            except RuntimeError as exc:
                raise RuntimeError(f"SPIKE {model}: {exc}") from exc
        served = self._spike_served_id[model]
        resp = client.chat.completions.create(
            model=served,
            max_tokens=max_tokens,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
            extra_body=extra_body or None,
        )
        choice = resp.choices[0]
        text = _check_answer(choice.message.content or "",
                             choice.finish_reason == "length")
        return text, 0.0

    def _call_openrouter(self, prompt: str, model: str, max_tokens: int,
                         extra_body: dict) -> tuple[str, float]:
        from openai import OpenAI
        if self._client is None:
            if not self.api_key:
                raise RuntimeError(
                    "openrouter backend needs api_key (constructor or "
                    "OPENROUTER_API_KEY env var)"
                )
            self._client = OpenAI(base_url=self.api_base, api_key=self.api_key,
                                   timeout=120.0, max_retries=2)
        resp = self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
            extra_body=extra_body or None,
            messages=[{"role": "user", "content": prompt}],
            # OpenRouter requires the HTTP-Referer header for some routes;
            # we send a generic one to identify the integration.
            extra_headers={
                "HTTP-Referer": "https://github.com/TimeSage-Series/TimeSage-EV",
                "X-Title":      "TimeSage-EV judge",
            },
        )
        choice = resp.choices[0]
        text = _check_answer(choice.message.content or "",
                             choice.finish_reason == "length")
        return text, 0.001

    # --------------- mock heuristics ---------------

    def _mock_response(self, prompt: str, kind: str) -> str:
        """Deterministic stubs keyed by prompt keywords. Lets unit tests run
        without API access."""
        # Allow explicit overrides
        for key_substr, response in self.mock_responses.items():
            if key_substr in prompt:
                return response
        # Dispatch on `kind` first. The prompt-keyword heuristics below are
        # kept as a fallback, but they are fragile: the quality prompt never
        # contains the word "rubric", so keyword matching alone fell through
        # to "OK" and pinned the quality axis to 0 for every mock run.
        if kind == "quality":
            return json.dumps({
                "required_hits": _mock_required_signals(prompt),
                "required_partial": [],
                "required_misses": [],
                "forbidden_violations": [],
                "rationale": "mock judge: all required signals present.",
            })

        # Heuristics — keep tests honest
        lp = prompt.lower()
        if "atomic" in lp and "decompose" in lp:
            # These must clear faithfulness._clean_facts (MIN_FACT_CHARS = 18),
            # otherwise every fact is filtered out, `atomic_facts` comes back
            # empty, and the faithfulness axis silently reports "skipped"
            # instead of exercising the scorer under --mock-judge.
            return json.dumps([
                "The reported index value matches the source series.",
                "The reported period label matches the requested period.",
            ])
        if "verify" in lp:
            # Default: tier1_supported
            return json.dumps({"verdict": "tier1_supported"})
        if "coverage" in lp or "communicate" in lp or "convey" in lp:
            return "YES"
        if "rubric" in lp:
            return json.dumps({
                "required_hits": ["all"],
                "forbidden_violations": [],
                "score": 1.0,
            })
        return "OK"


def _mock_required_signals(prompt: str) -> list[str]:
    """Pull the required-signal bullets out of a quality prompt.

    quality.py scores `hits / len(rubric.required_signals)`, so a mock that
    returns a fixed-size list would score an arbitrary fraction depending on
    the scenario's rubric. Echoing the signals back out of the prompt keeps
    the mock at a clean 100 for every tier.
    """
    marker = "Required signals"
    start = prompt.find(marker)
    if start == -1:
        return ["all"]
    block = prompt[start:].split("\n\n", 1)[0]
    out = [line.strip()[2:].strip()
           for line in block.splitlines() if line.strip().startswith("- ")]
    return [s for s in out if s and s != "(none declared)"] or ["all"]


def parse_json_maybe(text: str) -> Any:
    """Extract the first JSON object/array embedded in text, tolerating prose
    around it."""
    text = text.strip()
    # Direct attempt
    try:
        return json.loads(text)
    except Exception:
        pass
    # Find first balanced JSON span
    starts = [i for i, c in enumerate(text) if c in "{["]
    for s in starts:
        for e in range(len(text), s, -1):
            try:
                return json.loads(text[s:e])
            except Exception:
                continue
    return None


# ---------------------------------------------------------------------------
# Building a judge from settings
# ---------------------------------------------------------------------------

BACKENDS = ("mock", "anthropic", "claude_thinking", "claude_cli", "openrouter", "spike")


def build_judge(backend: str = "mock",
                model: Optional[str] = None,
                quality_model: Optional[str] = None,
                thinking: str = "middle",
                max_tokens: Optional[int] = None,
                extra_body: Optional[dict] = None,
                by_kind: Optional[dict] = None) -> Judge:
    """A Judge from CLI/config settings, filling in each backend's default
    models.

    `model` sets both kinds of call; `quality_model` overrides the model used
    for the report-quality axis only.
    """
    if backend not in BACKENDS:
        raise ValueError(f"unknown judge backend {backend!r}; choose from {BACKENDS}")
    if backend == "mock":
        return Judge(mock=True)

    overrides: dict = {"backend": backend}
    if model:
        overrides["model"] = model
        overrides["quality_model"] = model       # single model for both kinds
    elif backend == "openrouter":
        overrides["model"] = "openai/gpt-5.4"
        overrides["quality_model"] = "openai/gpt-5.4"
    elif backend == "claude_cli":
        overrides["model"] = "sonnet"
        overrides["quality_model"] = "sonnet"
    elif backend == "spike":
        overrides["model"] = "DeepSeek-V4-Flash"
        overrides["quality_model"] = "DeepSeek-V4-Flash"
    # An explicit quality model wins even when `model` is also set (so an
    # anthropic sonnet/haiku split or a spike Flash+Pro split works).
    if quality_model:
        overrides["quality_model"] = quality_model
    if backend == "claude_thinking":
        overrides["thinking_budget"] = THINKING_BUDGETS.get(thinking, 10000)
    if backend == "claude_cli":
        overrides["thinking_tier"] = thinking
    if max_tokens:
        overrides["max_tokens"] = int(max_tokens)
    if extra_body:
        overrides["extra_body"] = dict(extra_body)
    if by_kind:
        bad_kinds = sorted(set(by_kind) - set(JUDGE_KINDS))
        bad_opts = sorted({o for v in by_kind.values() for o in (v or {})} - set(KIND_OPTIONS))
        if bad_kinds or bad_opts:
            raise ValueError(f"judge by_kind: unknown kind(s) {bad_kinds} / option(s) {bad_opts}; "
                             f"kinds {JUDGE_KINDS}, options {KIND_OPTIONS}")
        overrides["by_kind"] = {k: dict(v or {}) for k, v in by_kind.items()}
    return Judge(**overrides)
