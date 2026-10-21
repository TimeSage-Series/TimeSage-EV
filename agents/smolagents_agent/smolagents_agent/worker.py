"""Subprocess entrypoint for the smolagents-based TimeSage agent.

Honors the evsandbox JSON-stdio contract. Two request modes:

  * single-period (legacy): one JSON request on stdin, one response on
    stdout, process exits. Used by `evsandbox run`.

  * episode (interactive):  multi-message stdin/stdout loop. Used by
    `evsandbox episode`. Wire:
        parent → child  : setup line   {"scenario_dir":..., "agent_args":...,
                                         "episode": {"interactive": true,
                                                     "episode_dir": ...,
                                                     "periods": ["p1","p2",...]}}
        loop, for each period:
          parent → child:  {"period":"p_i", "prompt":"<full prompt incl. last-period feedback>"}
          child  → parent: {"period":"p_i", "status":..., "structured_answer":...,
                            "report":..., "wall_ms":...}
        parent → child  : {"done": true}
        child  → parent : {"status":"ok", "mode":"episode", "periods":[...]}
    The child keeps ONE smolagents CodeAgent alive across all periods, so
    conversation memory accumulates naturally. Between periods, the runner
    refreshes the sandbox cwd so each period's CSV/gt_source matches that
    period's data.

See agents/README.md for the wire schema.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# -----------------------------------------------------------------------------
# CRITICAL: stdout isolation. smolagents' AgentLogger uses rich.Console which
# defaults to sys.stdout. In episode mode, the runner reads JSON responses
# from our subprocess stdout — ANY non-JSON byte written there (rich tables,
# error renderings, smolagents banners, stray `print()`) corrupts the pipe
# and the runner mis-parses the period response as agent_crash.
#
# Fix: reserve fd 1 (the original stdout) as the JSON channel by dup'ing
# it BEFORE any smolagents / rich / openai import, then point Python's
# sys.stdout at stderr so all incidental writes flow into stderr.log.
# Our _emit() writes to the dup'd handle directly. This must happen at
# module import time, before the agent code touches Rich.
# -----------------------------------------------------------------------------
_RESPONSE_STDOUT = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
sys.stdout = sys.stderr   # smolagents/rich writes (incidental) → stderr.log

from evsandbox.protocol import (
    ENV_AUDIT_PATH, ENV_CUTOFF, ENV_TRACE_PATH,
    STATUS_AGENT_CRASH, STATUS_INCOMPLETE, STATUS_OK,
    apply_period_cutoff,
)


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def _read_request() -> dict:
    line = sys.stdin.readline()
    if not line.strip():
        raise RuntimeError("smolagents_agent.worker: empty request on stdin")
    return json.loads(line)


def _emit(resp: dict) -> None:
    """Write one JSON line to the dedicated response channel (the dup'd
    original fd 1). NEVER writes via sys.stdout — that's been redirected
    to stderr so smolagents' Rich output can't corrupt the JSON stream.
    """
    _RESPONSE_STDOUT.write(json.dumps(resp) + "\n")
    _RESPONSE_STDOUT.flush()
    try:
        os.fsync(_RESPONSE_STDOUT.fileno())
    except OSError:
        pass


def _seed_trace(stream_path: Optional[Path], rows: list[dict]) -> None:
    """Append diagnostic rows to the streaming trace file (best-effort)."""
    if stream_path is None:
        return
    try:
        stream_path.parent.mkdir(parents=True, exist_ok=True)
        with stream_path.open("a") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
    except Exception:                                                  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Single-period mode (legacy / `evsandbox run`)
# ---------------------------------------------------------------------------

def _run_single(req: dict) -> int:
    from evbench.engine.tasks import load_scenario                                  # noqa: WPS433
    from .agent import TimeSageSmolAgent                                # noqa: WPS433
    from .lm import build_model                                         # noqa: WPS433

    scenario_dir    = Path(req["scenario_dir"]).resolve()
    period          = req["period"]
    prompt          = req["prompt"]
    agent_args      = req.get("agent_args") or {}
    lm_model        = agent_args.get("lm_model", "")
    episode_history = req.get("episode_history") or []
    max_steps       = int(agent_args.get("max_steps") or 12)
    verbosity       = int(agent_args.get("verbosity") or 0)

    audit_env = os.environ.get(ENV_AUDIT_PATH)
    audit_path = Path(audit_env) if audit_env else None
    cutoff = os.environ.get(ENV_CUTOFF, period)
    trace_env = os.environ.get(ENV_TRACE_PATH)
    stream_trace_path = Path(trace_env) if trace_env else None

    now = datetime.now(timezone.utc).isoformat()
    _seed_trace(stream_trace_path, [
        {"kind": "worker_start", "ts": now,
         "mode": "single", "lm_model": lm_model,
         "lm_provider": agent_args.get("lm_provider"),
         "max_steps": max_steps, "max_tokens": agent_args.get("max_tokens")},
        {"kind": "task", "task": prompt},
    ])

    scenario = load_scenario(scenario_dir)
    _seed_trace(stream_trace_path, [{"kind": "phase", "name": "build_model_start",
                                      "ts": datetime.now(timezone.utc).isoformat()}])
    model = build_model(lm_model, agent_args)
    _seed_trace(stream_trace_path, [{"kind": "phase", "name": "build_model_done",
                                      "ts": datetime.now(timezone.utc).isoformat(),
                                      "model_id": getattr(model, "model_id", None)}])

    agent = TimeSageSmolAgent(
        scenario, model,
        audit_path=audit_path, cutoff=cutoff,
        episode_history=episode_history,
        max_steps=max_steps, verbosity_level=verbosity,
        stream_trace_path=stream_trace_path,
    )

    t0 = time.time()
    structured, report, trace, usage = agent.run(prompt)
    wall_ms = int((time.time() - t0) * 1000)
    status = STATUS_OK if (structured and report) else STATUS_INCOMPLETE
    resp: dict = {
        "status":            status,
        "structured_answer": structured,
        "report":            report,
        "trace":             trace,
        "wall_ms":           wall_ms,
    }
    if usage:
        resp["usage"] = usage
    _emit(resp)
    return 0


# ---------------------------------------------------------------------------
# Episode mode (continuous conversation across periods)
# ---------------------------------------------------------------------------

def _save_memory_snapshot(agent, episode_dir: Path, period: str) -> Optional[str]:
    """Dump agent.memory.get_full_steps() so the episode can be resumed later.

    Returns an error string if the dump failed, else None. We never raise
    here — losing a snapshot is regrettable but should not abort the run.
    """
    try:
        snapshot = agent._agent.memory.get_full_steps()
        path = episode_dir / f"memory_after_{period}.json"
        path.write_text(json.dumps(snapshot, indent=2, default=str,
                                   ensure_ascii=False))
        return None
    except Exception as exc:                                           # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"[:300]


def _run_one_period(agent, scenario_dir: Path, episode_dir: Path,
                     stream_trace_path: Optional[Path],
                     period: str, prompt: str, is_first: bool, cwd: Path,
                     cutoff: str, memory_snapshots: bool = False) -> dict:
    """Execute one period in-loop. Returns the per-period response dict the
    parent expects. Always returns; never raises.

    The runner has already refreshed `cwd` to this period (CSV truncated at
    the period's release, gt_source/ with the newly-prior periods) before
    sending the period message."""
    instances_root = episode_dir / "instances"

    # Refresh per-period cutoff BEFORE agent.run. ENV_CUTOFF
    # was already set from the period message (apply_period_cutoff); the
    # agent's WebSearch tool captured its `_cutoff` at construction time
    # (against periods[0]), and without this update web_search would let
    # later-period information leak into early periods' answers.
    agent.set_period_cutoff(cutoff)

    _seed_trace(stream_trace_path, [
        {"kind": "period_start", "period": period, "is_first": is_first,
         "ts": datetime.now(timezone.utc).isoformat(),
         "prompt_chars": len(prompt)},
        {"kind": "task", "task": prompt, "period": period},
    ])

    # Reset captured (each period needs its own answer/report) but
    # NOT memory — that's the whole point of continuous mode.
    agent._final.captured = {"answer": None, "report": None}

    n_before = 0 if is_first else agent.memory_len()   # is_first resets memory
    t0 = time.time()
    try:
        agent._agent.run(prompt, return_full_result=True, reset=is_first)
    except Exception as exc:                                            # noqa: BLE001
        wall_ms = int((time.time() - t0) * 1000)
        _seed_trace(stream_trace_path, [
            {"kind": "period_error", "period": period,
             "phase": "agent.run", "error": repr(exc)[:300]},
        ])
        return {"period": period, "status": STATUS_AGENT_CRASH,
                "wall_ms": wall_ms, "error": repr(exc)[:300],
                "structured_answer": {}, "report": "",
                "usage": agent.usage_since(n_before)}

    wall_ms = int((time.time() - t0) * 1000)
    structured = agent._final.captured.get("answer") or {}
    if not isinstance(structured, dict):
        try:
            structured = json.loads(structured)
        except Exception:                                               # noqa: BLE001
            structured = {}
    report = agent._final.captured.get("report") or ""
    status = STATUS_OK if (structured and report) else STATUS_INCOMPLETE

    # Per-period artifacts under instances/<period>/
    pdir = instances_root / period
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "answer.json").write_text(
        json.dumps(structured, indent=2, ensure_ascii=False))
    (pdir / "report.md").write_text(report)
    (pdir / "meta.json").write_text(json.dumps({
        "period": period, "status": status, "wall_ms": wall_ms,
        "is_first": is_first,
        "ended_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))

    # Off by default: nothing in this agent reads the snapshot back, trace.jsonl
    # already holds every step, and each snapshot repeats every step's full
    # input messages, so they grow with the square of the episode length.
    snap_err = (_save_memory_snapshot(agent, episode_dir, period)
                if memory_snapshots else None)

    _seed_trace(stream_trace_path, [
        {"kind": "period_done", "period": period, "status": status,
         "wall_ms": wall_ms, "memory_snapshot_error": snap_err,
         "ts": datetime.now(timezone.utc).isoformat()},
    ])

    return {"period": period, "status": status, "wall_ms": wall_ms,
            "usage": agent.usage_since(n_before),
            "structured_answer": structured, "report": report}


def _run_episode(setup: dict) -> int:
    """Interactive episode loop. The setup line already arrived on stdin
    (parsed by main); from here we read one per-period request per iteration
    until a {"done": true} sentinel."""
    from evbench.engine.tasks import load_scenario                                  # noqa: WPS433
    from .agent import TimeSageSmolAgent                                # noqa: WPS433
    from .lm import build_model                                         # noqa: WPS433

    scenario_dir = Path(setup["scenario_dir"]).resolve()
    agent_args   = setup.get("agent_args") or {}
    lm_model     = agent_args.get("lm_model", "")
    max_steps    = int(agent_args.get("max_steps") or 12)
    verbosity    = int(agent_args.get("verbosity") or 0)
    memory_snapshots = bool(agent_args.get("memory_snapshots", False))

    episode      = setup["episode"]
    episode_dir  = Path(episode["episode_dir"]).resolve()
    episode_dir.mkdir(parents=True, exist_ok=True)
    (episode_dir / "instances").mkdir(parents=True, exist_ok=True)
    period_names: list[str] = list(episode.get("periods") or [])

    audit_env = os.environ.get(ENV_AUDIT_PATH)
    audit_path = Path(audit_env) if audit_env else None
    trace_env = os.environ.get(ENV_TRACE_PATH)
    stream_trace_path = Path(trace_env) if trace_env else episode_dir / "trace.jsonl"

    cwd = Path.cwd()

    now = datetime.now(timezone.utc).isoformat()
    _seed_trace(stream_trace_path, [
        {"kind": "worker_start", "ts": now,
         "mode": "episode", "lm_model": lm_model,
         "lm_provider": agent_args.get("lm_provider"),
         "n_periods": len(period_names),
         "max_steps": max_steps, "max_tokens": agent_args.get("max_tokens")},
    ])

    scenario = load_scenario(scenario_dir)
    _seed_trace(stream_trace_path, [{"kind": "phase", "name": "build_model_start",
                                      "ts": datetime.now(timezone.utc).isoformat()}])
    model = build_model(lm_model, agent_args)
    _seed_trace(stream_trace_path, [{"kind": "phase", "name": "build_model_done",
                                      "ts": datetime.now(timezone.utc).isoformat(),
                                      "model_id": getattr(model, "model_id", None)}])

    # The cutoff that web-search audits against changes per period; we
    # construct against the first announced period, which is also what the
    # runner put in ENV_CUTOFF at spawn. Each period message moves it on.
    cutoff = period_names[0] if period_names else ""
    agent = TimeSageSmolAgent(
        scenario, model,
        audit_path=audit_path, cutoff=cutoff,
        episode_history=[],
        max_steps=max_steps, verbosity_level=verbosity,
        stream_trace_path=stream_trace_path,
    )

    period_results: list[dict] = []
    n_seen = 0
    t_episode = time.time()

    # Memory-management policy. Four modes:
    #   "none"          — never compact (default; legacy behaviour)
    #   "interval"      — compact every memory_compact_interval periods
    #   "agent_decides" — compact iff the agent called the
    #                     `request_memory_compaction` tool during the
    #                     just-finished period. The tool is exposed by
    #                     TimeSageSmolAgent and sets a flag at call time.
    #   "hybrid"        — agent_decides OR auto when last-step input tokens
    #                     exceed memory_compact_token_threshold (safety net)
    #
    # If memory_compact_interval > 0 is set without memory_policy, the
    # legacy interval mode kicks in (back-compat with earlier runs).
    policy = (agent_args.get("memory_policy") or "").lower()
    compact_every = int(agent_args.get("memory_compact_interval") or 0)
    token_threshold = int(agent_args.get("memory_compact_token_threshold") or 200_000)
    if not policy and compact_every > 0:
        policy = "interval"   # implicit legacy mode
    if not policy:
        policy = "none"
    periods_done: list[str] = []
    answers_done: list[dict] = []

    while True:
        line = sys.stdin.readline()
        if not line:
            # Parent closed stdin without sending {"done": true}. Bail with
            # whatever we have; the parent will treat the loop as crashed.
            break
        try:
            msg = json.loads(line)
        except Exception as exc:                                        # noqa: BLE001
            _emit({"period": None, "status": STATUS_AGENT_CRASH,
                   "error": f"bad_request_json: {exc!r}",
                   "structured_answer": {}, "report": "", "wall_ms": 0})
            continue

        if msg.get("done"):
            break

        period = msg.get("period")
        prompt = msg.get("prompt") or ""
        if not period:
            _emit({"period": None, "status": STATUS_AGENT_CRASH,
                   "error": "missing_period",
                   "structured_answer": {}, "report": "", "wall_ms": 0})
            continue

        cutoff = apply_period_cutoff(msg)
        is_first = (n_seen == 0)
        result = _run_one_period(agent, scenario_dir, episode_dir,
                                  stream_trace_path, period, prompt,
                                  is_first, cwd, cutoff,
                                  memory_snapshots=memory_snapshots)
        n_seen += 1
        period_results.append(result)
        periods_done.append(period)
        answers_done.append(result.get("structured_answer") or {})

        # ----- Memory policy: decide whether to compact AFTER this period.
        triggers: list[str] = []
        agent_requested = bool(getattr(agent._compact, "requested", False))
        agent_request_reason = (getattr(agent._compact, "last_reason", "")
                                if agent_requested else "")

        # Most recent step's *real* provider-reported input_tokens.
        # smolagents attaches `token_usage` to each ActionStep after the LM
        # call returns (see agent.py:_extract_usage). chars/4 was off by
        # ~3.7× on Kimi (BPE) — JSON / numerics / mixed-script content
        # tokenize denser than English prose. Walk back to the most recent
        # step with a non-null input_tokens; fall back to 0 only during
        # cold start before any LM call has completed.
        last_input_tokens = 0
        try:
            for step in reversed(agent._agent.memory.steps):
                tu = getattr(step, "token_usage", None)
                if tu is None:
                    continue
                ti = getattr(tu, "input_tokens", None)
                if ti is None and isinstance(tu, dict):
                    ti = tu.get("input_tokens")
                if ti:
                    last_input_tokens = int(ti)
                    break
        except Exception:                                               # noqa: BLE001
            last_input_tokens = 0

        if policy == "interval" and compact_every > 0 \
                and n_seen % compact_every == 0:
            triggers.append(f"interval({compact_every})")
        if policy in ("agent_decides", "hybrid") and agent_requested:
            triggers.append("agent_marker")
        if policy == "hybrid" and last_input_tokens > token_threshold:
            triggers.append(f"threshold({last_input_tokens}>{token_threshold})")

        _emit(result)

        if triggers:
            _seed_trace(stream_trace_path, [
                {"kind": "memory_compact_start",
                 "ts": datetime.now(timezone.utc).isoformat(),
                 "after_period": period,
                 "n_periods": n_seen,
                 "policy": policy,
                 "triggers": triggers,
                 "agent_reason": agent_request_reason,
                 "last_input_tokens": last_input_tokens}
            ])
            t_c = time.time()
            try:
                report_compact = agent.compact_memory(
                    list(periods_done), list(answers_done))
            except Exception as exc:                                    # noqa: BLE001
                report_compact = {"error": f"{type(exc).__name__}: {exc}"}
            wall_compact = int((time.time() - t_c) * 1000)
            try:
                comp_dir = episode_dir / "compactions"
                comp_dir.mkdir(parents=True, exist_ok=True)
                (comp_dir / f"after_period_{n_seen:02d}_{period}.md").write_text(
                    (report_compact or {}).get("summary") or
                    f"<empty summary; error: {(report_compact or {}).get('error','?')}>"
                )
            except Exception:                                           # noqa: BLE001
                pass
            # Clear the agent's compaction-request flag so the next
            # period's call (if any) starts fresh.
            try:
                agent._compact.reset()
            except Exception:                                           # noqa: BLE001
                pass
            _seed_trace(stream_trace_path, [
                {"kind": "memory_compact_done",
                 "ts": datetime.now(timezone.utc).isoformat(),
                 "after_period": period,
                 "wall_ms": wall_compact,
                 "triggers": triggers,
                 **{k: v for k, v in (report_compact or {}).items()
                    if k != "summary"},
                 "summary_chars": len(((report_compact or {}).get("summary") or ""))}
            ])
        elif policy != "none":
            # Log non-triggers too so the trace is fully auditable
            _seed_trace(stream_trace_path, [
                {"kind": "memory_compact_skipped",
                 "ts": datetime.now(timezone.utc).isoformat(),
                 "after_period": period,
                 "policy": policy,
                 "last_input_tokens": last_input_tokens,
                 "agent_requested": agent_requested}
            ])
            # Even when not triggered, clear stale agent flag if set —
            # otherwise the request leaks into a later period.
            if agent_requested:
                try:
                    agent._compact.reset()
                except Exception:                                       # noqa: BLE001
                    pass

    total_ms = int((time.time() - t_episode) * 1000)
    _emit({
        "status":  "ok",
        "mode":    "episode",
        "periods": period_results,
        "wall_ms": total_ms,
    })
    return 0


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        req = _read_request()
    except Exception as exc:                                          # noqa: BLE001
        _emit({"status": STATUS_AGENT_CRASH,
               "error":  f"request_parse: {exc!r}"})
        return 2

    try:
        if req.get("episode"):
            return _run_episode(req)        # `req` is the setup line; loop reads more
        return _run_single(req)
    except Exception as exc:                                          # noqa: BLE001
        _emit({"status":    STATUS_AGENT_CRASH,
               "error":     repr(exc),
               "traceback": traceback.format_exc()[:4000]})
        return 1


if __name__ == "__main__":
    sys.exit(main())
