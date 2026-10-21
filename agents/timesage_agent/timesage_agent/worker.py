"""TimeSage skill-aware subprocess entrypoint.

Mirrors `smolagents_agent.worker` exactly (stdin/stdout JSON contract, the
stdout-fd duping discipline, the episode-vs-single dispatch, memory-policy
handling, etc.) so the existing `evsandbox.cli` runner can drive us without
any framework changes. The ONLY differences vs. smolagents_agent.worker:

  1. We compute a per-sweep `skill_dir` from the trace/episode path:
        skill_dir = <exp>/<target>/skills/<llm-slug>/
     Override with TIMESAGE_SKILL_DIR env var if you need cross-sweep
     sharing.

  2. After `TimeSageSmolAgent` is constructed, we inject two extra tools
     into its inner `_agent.tools` dict (`induct_skill`, `retrieve_skill`)
     plus one Tool per previously-saved skill (dynamically built via
     `skill_store.build_skill_tool`).

  3. Just before each `agent.run()` call we prepend a markdown "Available
     skills" index block to the prompt — mirrors Claude Code's pattern of
     showing `(name, description)` upfront so the agent can pick without
     paying a retrieval round-trip.

  4. After each period in episode mode, if any new skill was inducted this
     period, we re-scan skill_dir and add the new Tool to `_agent.tools`
     so the agent can invoke it from the next period onwards.
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
# CRITICAL: stdout isolation (see smolagents_agent.worker for full rationale).
# Must run BEFORE smolagents/rich/openai imports — those write to fd 1.
# -----------------------------------------------------------------------------
_RESPONSE_STDOUT = os.fdopen(os.dup(1), "w", buffering=1, encoding="utf-8")
sys.stdout = sys.stderr

from evsandbox.protocol import (
    ENV_AUDIT_PATH, ENV_CUTOFF, ENV_TRACE_PATH,
    STATUS_AGENT_CRASH, STATUS_INCOMPLETE, STATUS_OK,
    apply_period_cutoff,
)


# ---------------------------------------------------------------------------
# IO helpers (verbatim from smolagents_agent.worker — duplicated to avoid
# the import-time stdout-redirect coupling).
# ---------------------------------------------------------------------------

def _read_request() -> dict:
    line = sys.stdin.readline()
    if not line.strip():
        raise RuntimeError("timesage_agent.worker: empty request on stdin")
    return json.loads(line)


def _emit(resp: dict) -> None:
    _RESPONSE_STDOUT.write(json.dumps(resp) + "\n")
    _RESPONSE_STDOUT.flush()
    try:
        os.fsync(_RESPONSE_STDOUT.fileno())
    except OSError:
        pass


def _seed_trace(stream_path: Optional[Path], rows: list[dict]) -> None:
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
# Skill-dir derivation
# ---------------------------------------------------------------------------

def _slugify_llm(s: str) -> str:
    """Same slugification as evsandbox.runner._slugify_llm."""
    import re as _re
    if not s:
        return "unknown"
    out = _re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("._-")
    return out or "unknown"


def _resolve_skill_dir(
    *,
    trace_path: Optional[Path],
    episode_dir: Optional[Path],
    llm_slug: str,
    scenario_id: str,
) -> Path:
    """Compute the per-(sweep × llm × scenario) skill-library directory.

    Skills are scoped to one scenario by default — different scenarios
    have different CSV schemas, period vocabularies, and answer shapes,
    so a `classify_butter_band` skill is meaningless for an oil-market
    scenario. Pooling skills across scenarios was the v1 mistake.

    Precedence:
      1. env TIMESAGE_SKILL_DIR    — explicit override. We still append
                                      `<llm_slug>/<scenario_id>` so an
                                      env override can be shared across
                                      sweeps while still isolating skills
                                      per (llm, scenario).
      2. episode_dir given         — walk 3 up to <target>;
                                      skill_dir = <target>/skills/<llm>/<scenario>
      3. trace_path given          — walk up to find the dir matching llm_slug,
                                      target_dir is its parent
      4. fallback                  — /tmp/timesage_skill_default/<llm>/<scenario>
    """
    env_override = os.environ.get("TIMESAGE_SKILL_DIR")
    if env_override:
        return Path(env_override) / llm_slug / scenario_id

    if episode_dir is not None:
        # episode_dir = <exp>/<target>/<llm-slug>/<tier>/<scenario>/
        # → <target> = episode_dir.parent.parent.parent
        try:
            target_dir = episode_dir.parent.parent.parent
            return target_dir / "skills" / llm_slug / scenario_id
        except IndexError:
            pass

    if trace_path is not None:
        # Walk up looking for a dir whose name == llm_slug; target_dir is its parent
        cur = trace_path.parent
        while cur and cur != cur.parent:
            if cur.name == llm_slug:
                return cur.parent / "skills" / llm_slug / scenario_id
            cur = cur.parent

    return Path("/tmp") / "timesage_skill_default" / llm_slug / scenario_id


# ---------------------------------------------------------------------------
# Skill-tool wiring helpers
# ---------------------------------------------------------------------------

def _inject_skill_tools(agent, skill_dir: Path,
                         induct_tool, retrieve_tool,
                         stream_trace_path: Optional[Path]) -> int:
    """Add induct_skill, retrieve_skill, and all saved-skill tools to
    `agent._agent.tools`. Returns the number of saved-skill tools added.
    """
    from . import skill_store

    agent._agent.tools[induct_tool.name]   = induct_tool
    agent._agent.tools[retrieve_tool.name] = retrieve_tool

    skill_tools = skill_store.build_all_skill_tools(skill_dir)
    for tool in skill_tools:
        agent._agent.tools[tool.name] = tool

    _seed_trace(stream_trace_path, [
        {"kind": "phase", "name": "skills_loaded",
         "ts": datetime.now(timezone.utc).isoformat(),
         "skill_dir": str(skill_dir),
         "n_skills_loaded_as_tools": len(skill_tools),
         "loaded_names": [t.name for t in skill_tools]},
    ])
    return len(skill_tools)


def _refresh_skill_tools_after_period(agent, skill_dir: Path,
                                       induct_tool,
                                       stream_trace_path: Optional[Path]) -> None:
    """After a period, if `induct_tool.saved_this_period` is non-empty, load
    the new skills and add them to the agent's tools dict.
    """
    from . import skill_store

    if not induct_tool.saved_this_period:
        return
    new_names = list(induct_tool.saved_this_period)
    # Reload each by name; if the dynamic build fails we just skip.
    added = []
    for name in new_names:
        md_path = skill_dir / f"{name}.md"
        if not md_path.exists():
            continue
        try:
            tool = skill_store.build_skill_tool(md_path)
        except Exception as exc:                                       # noqa: BLE001
            _seed_trace(stream_trace_path, [
                {"kind": "skill_refresh_error", "name": name,
                 "error": f"{type(exc).__name__}: {exc}",
                 "ts": datetime.now(timezone.utc).isoformat()},
            ])
            continue
        agent._agent.tools[tool.name] = tool
        added.append(tool.name)
    induct_tool.saved_this_period = []
    if added:
        _seed_trace(stream_trace_path, [
            {"kind": "phase", "name": "skills_refreshed",
             "ts": datetime.now(timezone.utc).isoformat(),
             "added": added,
             "available_now": [n for n, _ in skill_store.list_skills(skill_dir)]},
        ])


def _prefix_with_skill_index(prompt: str, skill_dir: Path) -> str:
    from . import skill_store
    block = skill_store.build_skill_index_block(skill_dir)
    return block + prompt if block else prompt


# ---------------------------------------------------------------------------
# Single-period mode
# ---------------------------------------------------------------------------

def _run_single(req: dict) -> int:
    from evbench.engine.tasks import load_scenario                                  # noqa: WPS433
    from smolagents_agent.agent import TimeSageSmolAgent                # noqa: WPS433
    from smolagents_agent.lm import build_model                         # noqa: WPS433
    from .tools import InductSkillTool, RetrieveSkillTool

    scenario_dir    = Path(req["scenario_dir"]).resolve()
    period          = req["period"]
    prompt          = req["prompt"]
    agent_args      = req.get("agent_args") or {}
    lm_model        = agent_args.get("lm_model", "")
    llm_slug        = _slugify_llm(lm_model)
    episode_history = req.get("episode_history") or []
    max_steps       = int(agent_args.get("max_steps") or 12)
    verbosity       = int(agent_args.get("verbosity") or 0)

    audit_env = os.environ.get(ENV_AUDIT_PATH)
    audit_path = Path(audit_env) if audit_env else None
    cutoff = os.environ.get(ENV_CUTOFF, period)
    trace_env = os.environ.get(ENV_TRACE_PATH)
    stream_trace_path = Path(trace_env) if trace_env else None

    # Need scenario_id BEFORE resolving skill_dir (skill libraries are
    # scoped per-scenario). Loading the scenario is cheap (yaml parse).
    scenario = load_scenario(scenario_dir)
    scenario_id = getattr(scenario, "scenario_id", scenario_dir.name)

    skill_dir = _resolve_skill_dir(trace_path=stream_trace_path,
                                    episode_dir=None,
                                    llm_slug=llm_slug,
                                    scenario_id=scenario_id)
    skill_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    _seed_trace(stream_trace_path, [
        {"kind": "worker_start", "ts": now,
         "mode": "single", "lm_model": lm_model,
         "lm_provider": agent_args.get("lm_provider"),
         "max_steps": max_steps, "max_tokens": agent_args.get("max_tokens"),
         "harness": "timesage", "skill_dir": str(skill_dir),
         "scenario_id": scenario_id},
        {"kind": "task", "task": prompt},
    ])
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

    induct_tool   = InductSkillTool(skill_dir,
                                     scenario_id=scenario_id,
                                     period=period, llm_slug=llm_slug)
    retrieve_tool = RetrieveSkillTool(skill_dir)
    _inject_skill_tools(agent, skill_dir, induct_tool, retrieve_tool,
                         stream_trace_path)

    augmented = _prefix_with_skill_index(prompt, skill_dir)

    t0 = time.time()
    structured, report, trace, usage = agent.run(augmented)
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
                     cutoff: str,
                     skill_dir: Path, induct_tool,
                     auto_induct_cfg: Optional[dict] = None) -> dict:
    """Execute one period. Like smolagents_agent's _run_one_period but with
    skill-index prepending and a post-period skill-tool refresh. The runner
    has already refreshed `cwd` to this period."""
    instances_root = episode_dir / "instances"

    agent.set_period_cutoff(cutoff)       # ENV_CUTOFF: apply_period_cutoff()

    # Refresh InductSkillTool's per-period context fields so any new skill
    # saved this period records the correct (scenario, period) provenance.
    induct_tool.update_context(scenario_id=getattr(agent.scenario, "scenario_id", ""),
                                period=period)

    # Prepend the skill-index block. The block reflects the library AS OF
    # this period's start; any skill the agent inducts during this period
    # appears in the NEXT period's index (since the new tool only becomes
    # available after the period boundary).
    augmented_prompt = _prefix_with_skill_index(prompt, skill_dir)

    _seed_trace(stream_trace_path, [
        {"kind": "period_start", "period": period, "is_first": is_first,
         "ts": datetime.now(timezone.utc).isoformat(),
         "prompt_chars": len(augmented_prompt),
         "skill_index_chars": len(augmented_prompt) - len(prompt)},
        {"kind": "task", "task": augmented_prompt, "period": period},
    ])

    agent._final.captured = {"answer": None, "report": None}

    n_before = 0 if is_first else agent.memory_len()   # is_first resets memory
    t0 = time.time()
    try:
        agent._agent.run(augmented_prompt, return_full_result=True, reset=is_first)
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

    snap_err = _save_memory_snapshot(agent, episode_dir, period)

    _seed_trace(stream_trace_path, [
        {"kind": "period_done", "period": period, "status": status,
         "wall_ms": wall_ms, "memory_snapshot_error": snap_err,
         "ts": datetime.now(timezone.utc).isoformat(),
         "skills_saved_this_period": list(induct_tool.saved_this_period)},
    ])

    # Auto-induction: optionally run a 1-shot LLM curation pass right
    # here so it sees the just-finished period's actions while still in
    # context. The pass is silent (no exception escapes) — failure to
    # induct should never block the episode.
    if (auto_induct_cfg or {}).get("enabled"):
        from . import auto_induct
        _seed_trace(stream_trace_path, [
            {"kind": "auto_induct_start",
             "ts": datetime.now(timezone.utc).isoformat(),
             "period": period},
        ])
        try:
            ai_result = auto_induct.auto_induct_period(
                model=auto_induct_cfg["model"],
                trace_path=stream_trace_path,
                skill_dir=skill_dir,
                period=period,
                scenario_id=getattr(agent.scenario, "scenario_id", ""),
                tier=getattr(agent.scenario, "tier", ""),
                llm_slug=auto_induct_cfg["llm_slug"],
                score=None,   # Score not available here; runner scores after subprocess returns.
                final_answer=structured,
                min_score=float(auto_induct_cfg.get("min_score", 0)),
                only_if_ok=True,
                period_status=status,
            )
        except Exception as exc:                                       # noqa: BLE001
            ai_result = {"decision": "exception", "error": repr(exc)[:300]}
        _seed_trace(stream_trace_path, [
            {"kind": "auto_induct_done",
             "ts": datetime.now(timezone.utc).isoformat(),
             "period": period,
             **{k: v for k, v in ai_result.items()
                if k in ("decision","saved_name","error","model_reply_chars")}},
        ])
        # If auto-induct just saved one, make it visible to the
        # refresh routine below so it gets registered as a tool.
        if ai_result.get("saved_name"):
            induct_tool.saved_this_period.append(ai_result["saved_name"])

    # Make any newly-inducted skills callable from the next period.
    _refresh_skill_tools_after_period(agent, skill_dir, induct_tool,
                                       stream_trace_path)

    return {"period": period, "status": status, "wall_ms": wall_ms,
            "usage": agent.usage_since(n_before),
            "structured_answer": structured, "report": report}


def _detect_resume_state(episode_dir: Path) -> tuple[set, Optional[Path]]:
    """For an existing episode_dir, return:
      * set of period names that ALREADY have meta.json status=ok (skip these);
      * path to the latest memory_after_<period>.json (most-recently-modified),
        or None if no snapshot exists.
    Used by `--agent-arg resume=on` to skip done work + carry prior memory.
    """
    done: set[str] = set()
    inst_root = episode_dir / "instances"
    if inst_root.exists():
        for p_dir in inst_root.iterdir():
            mf = p_dir / "meta.json"
            if mf.exists():
                try:
                    meta = json.load(open(mf))
                    if meta.get("status") == "ok":
                        done.add(p_dir.name)
                except Exception:                                       # noqa: BLE001
                    pass
    snaps = sorted(episode_dir.glob("memory_after_*.json"),
                    key=lambda p: p.stat().st_mtime)
    last_snap = snaps[-1] if snaps else None
    return done, last_snap


def _build_carry_from_memory(memory_path: Path, model, scenario,
                              done_periods: set,
                              stream_trace_path: Optional[Path]) -> str:
    """Read memory_after_<period>.json + ask the LLM to summarise it into a
    carry text. Same shape as TimeSageSmolAgent.compact_memory's summarizer
    output but built from a JSON snapshot instead of an in-process agent.
    """
    from smolagents.models import ChatMessage, MessageRole              # noqa: WPS433

    try:
        snapshot = json.load(open(memory_path))
    except Exception as exc:                                            # noqa: BLE001
        _seed_trace(stream_trace_path, [
            {"kind": "resume_carry_error", "memory_path": str(memory_path),
             "error": f"load: {exc!r}"},
        ])
        return ""

    # Build a transcript-ish string from the snapshot (list of step dicts)
    parts: list[str] = []
    for st in snapshot:
        if not isinstance(st, dict): continue
        if "task" in st and st.get("task"):
            parts.append(f"## Initial task\n{str(st['task'])[:1500]}")
            continue
        n = st.get("step_number")
        code = st.get("code_action") or ""
        obs  = (st.get("observations") or "")[:600]
        err  = st.get("error")
        block = [f"### Step {n}"]
        if code: block.append(f"Code:\n```python\n{code[:1200]}\n```")
        if obs:  block.append(f"Observation:\n{obs}")
        if err:  block.append(f"Error: {str(err)[:200]}")
        parts.append("\n".join(block))
    transcript = ("\n\n".join(parts))[:40_000]

    period = memory_path.stem.replace("memory_after_", "")
    summarizer = (
        f"You are a CONTEXT COMPRESSOR for a resumed multi-period evaluation. "
        f"An agent completed {len(done_periods)} periods of scenario "
        f"`{getattr(scenario, 'scenario_id', '?')}` (tier="
        f"{getattr(scenario, 'tier', '?')}) up through `{period}`. The "
        f"transcript below is its last-period working memory. Produce a "
        f"tight summary (≤ 1500 tokens) the SAME agent will read INSTEAD of "
        f"the full transcript before resuming with the next period.\n"
        f"\nCover concretely:\n"
        f"  1. **Data layout** — CSV column names + how the agent indexes them.\n"
        f"  2. **Working code idioms** — reusable patterns the agent has been "
        f"using (loading, classifying, etc.).\n"
        f"  3. **Error patterns** — sandbox restrictions / failed tactics to avoid.\n"
        f"  4. **Periods completed (last few + their answers)** — what was "
        f"submitted, what the score feedback said.\n"
        f"\nReturn ONLY the summary body — no preamble, no code fences "
        f"around it. Plain markdown bullets are fine.\n"
        f"\n--- TRANSCRIPT (last period: {period}) ---\n{transcript}\n"
    )
    msgs = [ChatMessage(role=MessageRole.USER,
                         content=[{"type":"text","text":summarizer}])]
    try:
        resp = model.generate(messages=msgs, stop_sequences=None)
    except Exception as exc:                                            # noqa: BLE001
        _seed_trace(stream_trace_path, [
            {"kind": "resume_carry_error", "memory_path": str(memory_path),
             "error": f"llm_call: {type(exc).__name__}: {exc!s:.200}"},
        ])
        return ""
    c = resp.content
    if isinstance(c, list):
        c = "\n".join(part.get("text","") if isinstance(part, dict) else str(part)
                      for part in c)
    return str(c or "")


def _synthetic_period_response(episode_dir: Path, period: str) -> Optional[dict]:
    """Build a response dict from an already-completed period's on-disk
    artifacts. Returns None if files missing.
    """
    pdir = episode_dir / "instances" / period
    meta_p = pdir / "meta.json"
    rr_p   = pdir / "run_record.json"
    if not (meta_p.exists() and rr_p.exists()):
        return None
    try:
        meta = json.load(open(meta_p))
        rr   = json.load(open(rr_p))
    except Exception:                                                   # noqa: BLE001
        return None
    return {
        "period":            period,
        "status":            meta.get("status", "ok"),
        "wall_ms":           meta.get("wall_ms", 0),
        "structured_answer": rr.get("structured_answer", {}),
        "report":            rr.get("report", ""),
        "resumed_from_disk": True,
    }


def _run_episode(setup: dict) -> int:
    from evbench.engine.tasks import load_scenario                                  # noqa: WPS433
    from smolagents_agent.agent import TimeSageSmolAgent                # noqa: WPS433
    from smolagents_agent.lm import build_model                         # noqa: WPS433
    from .tools import InductSkillTool, RetrieveSkillTool
    from smolagents.memory import TaskStep                              # noqa: WPS433

    scenario_dir = Path(setup["scenario_dir"]).resolve()
    agent_args   = setup.get("agent_args") or {}
    lm_model     = agent_args.get("lm_model", "")
    llm_slug     = _slugify_llm(lm_model)
    max_steps    = int(agent_args.get("max_steps") or 12)
    verbosity    = int(agent_args.get("verbosity") or 0)

    episode      = setup["episode"]
    episode_dir  = Path(episode["episode_dir"]).resolve()
    episode_dir.mkdir(parents=True, exist_ok=True)
    (episode_dir / "instances").mkdir(parents=True, exist_ok=True)
    period_names: list[str] = list(episode.get("periods") or [])

    audit_env = os.environ.get(ENV_AUDIT_PATH)
    audit_path = Path(audit_env) if audit_env else None
    trace_env = os.environ.get(ENV_TRACE_PATH)
    stream_trace_path = Path(trace_env) if trace_env else episode_dir / "trace.jsonl"

    # Need scenario_id BEFORE resolving skill_dir (skill libraries are
    # scoped per-scenario — see _resolve_skill_dir docstring).
    scenario = load_scenario(scenario_dir)
    scenario_id = getattr(scenario, "scenario_id", scenario_dir.name)

    skill_dir = _resolve_skill_dir(trace_path=stream_trace_path,
                                    episode_dir=episode_dir,
                                    llm_slug=llm_slug,
                                    scenario_id=scenario_id)
    skill_dir.mkdir(parents=True, exist_ok=True)

    cwd = Path.cwd()

    now = datetime.now(timezone.utc).isoformat()
    _seed_trace(stream_trace_path, [
        {"kind": "worker_start", "ts": now,
         "mode": "episode", "lm_model": lm_model,
         "lm_provider": agent_args.get("lm_provider"),
         "n_periods": len(period_names),
         "max_steps": max_steps, "max_tokens": agent_args.get("max_tokens"),
         "harness": "timesage", "skill_dir": str(skill_dir),
         "scenario_id": scenario_id},
    ])
    _seed_trace(stream_trace_path, [{"kind": "phase", "name": "build_model_start",
                                      "ts": datetime.now(timezone.utc).isoformat()}])
    model = build_model(lm_model, agent_args)
    _seed_trace(stream_trace_path, [{"kind": "phase", "name": "build_model_done",
                                      "ts": datetime.now(timezone.utc).isoformat(),
                                      "model_id": getattr(model, "model_id", None)}])

    cutoff = period_names[0] if period_names else ""
    agent = TimeSageSmolAgent(
        scenario, model,
        audit_path=audit_path, cutoff=cutoff,
        episode_history=[],
        max_steps=max_steps, verbosity_level=verbosity,
        stream_trace_path=stream_trace_path,
    )

    induct_tool   = InductSkillTool(skill_dir,
                                     scenario_id=scenario_id,
                                     period="", llm_slug=llm_slug)
    retrieve_tool = RetrieveSkillTool(skill_dir)
    _inject_skill_tools(agent, skill_dir, induct_tool, retrieve_tool,
                         stream_trace_path)

    # ----------------------------------------------------------------------
    # Resume support (opt-in via agent_args.resume=on).
    # If enabled, we (a) gather the set of periods already complete on disk,
    # (b) synthesise responses for them straight from run_record.json, and
    # (c) carry the agent's prior memory via an LLM-built summary injected
    # as the agent's first TaskStep — same trick as compact_memory uses
    # between periods, just sourced from a JSON snapshot instead of an
    # in-process memory object.
    # ----------------------------------------------------------------------
    resume_enabled = str(agent_args.get("resume") or "off").lower() == "on"
    done_periods: set[str] = set()
    last_snap: Optional[Path] = None
    carry_text = ""
    if resume_enabled:
        done_periods, last_snap = _detect_resume_state(episode_dir)
        _seed_trace(stream_trace_path, [
            {"kind": "resume_init",
             "ts": datetime.now(timezone.utc).isoformat(),
             "done_periods_count": len(done_periods),
             "memory_snapshot": str(last_snap) if last_snap else None},
        ])
        if last_snap is not None:
            carry_text = _build_carry_from_memory(
                last_snap, model, scenario, done_periods, stream_trace_path)
            if carry_text:
                # Reset memory and inject the carry summary as a TaskStep.
                # Subsequent agent.run(reset=False) will see this as prior context.
                try:
                    agent._agent.memory.reset()
                    agent._agent.memory.steps.append(TaskStep(task=(
                        f"# Resumed from prior periods of scenario "
                        f"`{scenario_id}`\n\n"
                        f"You ALREADY completed {len(done_periods)} period(s). "
                        f"Below is the compressed memory of that work — read "
                        f"it as your starting context. Skill library + tool "
                        f"list are unchanged.\n\n{carry_text}\n\n---\n"
                        f"You will now continue with the NEXT unfinished period."
                    )))
                except Exception as exc:                                # noqa: BLE001
                    _seed_trace(stream_trace_path, [
                        {"kind": "resume_carry_error",
                         "error": f"inject: {type(exc).__name__}: {exc}"},
                    ])
                _seed_trace(stream_trace_path, [
                    {"kind": "resume_carry_loaded",
                     "ts": datetime.now(timezone.utc).isoformat(),
                     "carry_chars": len(carry_text)},
                ])

    # Auto-induction config. Opt-in via agent_args:
    #   auto_induction=on|off  (default off)
    #   auto_induction_min_score=N  (default 0; only induct if score ≥ N)
    # We reuse the SAME model the agent uses — no extra provider config.
    auto_induct_cfg: Optional[dict] = None
    if str(agent_args.get("auto_induction") or "off").lower() == "on":
        auto_induct_cfg = {
            "enabled":   True,
            "model":     model,
            "llm_slug":  llm_slug,
            "min_score": float(agent_args.get("auto_induction_min_score") or 0),
        }
        _seed_trace(stream_trace_path, [
            {"kind": "phase", "name": "auto_induction_armed",
             "ts": datetime.now(timezone.utc).isoformat(),
             "min_score": auto_induct_cfg["min_score"]},
        ])

    period_results: list[dict] = []
    n_seen = 0
    t_episode = time.time()

    policy = (agent_args.get("memory_policy") or "").lower()
    compact_every = int(agent_args.get("memory_compact_interval") or 0)
    token_threshold = int(agent_args.get("memory_compact_token_threshold") or 200_000)
    if not policy and compact_every > 0:
        policy = "interval"
    if not policy:
        policy = "none"
    periods_done: list[str] = []
    answers_done: list[dict] = []

    while True:
        line = sys.stdin.readline()
        if not line:
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

        # Resume: synthesise response from disk if this period already
        # completed successfully. We do NOT touch the agent — its memory
        # already has the carry summary representing this work, and the
        # judge/runner will not re-score (run_record already exists).
        if resume_enabled and period in done_periods:
            synth = _synthetic_period_response(episode_dir, period)
            if synth is not None:
                _seed_trace(stream_trace_path, [
                    {"kind": "resume_skip",
                     "ts": datetime.now(timezone.utc).isoformat(),
                     "period": period, "reason": "already_ok"},
                ])
                _emit(synth)
                # Don't append to period_results/periods_done/answers_done
                # since compaction policy + auto-induct only apply to
                # freshly-run periods this session.
                continue

        # is_first → smolagents resets memory before run. When we resumed
        # with a carry summary, we MUST NOT reset on the first real run —
        # that would wipe the carry. Treat carry_text as if it's already
        # equivalent to having run a prior period.
        is_first = (n_seen == 0 and not carry_text)
        result = _run_one_period(agent, scenario_dir, episode_dir,
                                  stream_trace_path, period, prompt,
                                  is_first, cwd, cutoff, skill_dir, induct_tool,
                                  auto_induct_cfg=auto_induct_cfg)
        n_seen += 1
        period_results.append(result)
        periods_done.append(period)
        answers_done.append(result.get("structured_answer") or {})

        # Memory-policy bookkeeping (identical to smolagents_agent.worker)
        triggers: list[str] = []
        agent_requested = bool(getattr(agent._compact, "requested", False))
        agent_request_reason = (getattr(agent._compact, "last_reason", "")
                                if agent_requested else "")

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
            _seed_trace(stream_trace_path, [
                {"kind": "memory_compact_skipped",
                 "ts": datetime.now(timezone.utc).isoformat(),
                 "after_period": period,
                 "policy": policy,
                 "last_input_tokens": last_input_tokens,
                 "agent_requested": agent_requested}
            ])
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
            return _run_episode(req)
        return _run_single(req)
    except Exception as exc:                                          # noqa: BLE001
        _emit({"status":    STATUS_AGENT_CRASH,
               "error":     repr(exc),
               "traceback": traceback.format_exc()[:4000]})
        return 1


if __name__ == "__main__":
    sys.exit(main())
