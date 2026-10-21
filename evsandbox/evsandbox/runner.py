"""End-to-end runner: engine (task → prompt, sandbox) → AGENT (subprocess) → record → score.

The runner is agent-agnostic. It only knows the JSON-stdio contract in
`evsandbox.protocol`. Different agents are selected via `--agent-cmd
"python -m smolagents_agent.worker"`.

In-process execution has been removed: subprocess is the canonical seam.
If you need to debug an agent, run its worker module directly with a JSON
file on stdin.

"""
from __future__ import annotations

import collections
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))                                        # for evbench.*

from evbench.engine import (                                           # noqa: E402
    build_world, episode_prompt, load_scenario, refresh_world, task_prompt,
)
from evbench.evaluator.judge import Judge                              # noqa: E402
from evbench.evaluator.cli import _score_one as _scoresuite_score_one  # noqa: E402

from .isolation import OUT_DIR, bwrap_command                         # noqa: E402
from .feedback import (                                                # noqa: E402
    FeedbackMode, build_feedback, render_scoring_unavailable,
)
import select as _select                                               # noqa: E402
from .protocol import (                                               # noqa: E402
    ENV_AUDIT_PATH, ENV_CUTOFF, ENV_RUN_ID, ENV_SEARXNG, ENV_TRACE_PATH,
    STATUS_AGENT_CRASH, STATUS_INCOMPLETE, STATUS_OK, STATUS_TIMEOUT,
    STATUS_LEAKAGE,
)


RUNS_ROOT = REPO / "evsandbox" / "runs"     # legacy; kept for compat with old imports
EXP_ROOT  = REPO / "exp"


def _slugify_llm(s: str) -> str:
    """Filesystem-safe slug for the LLM identifier used in run-path.

    Allows letters, digits, ``.``, ``_``, ``-``. Everything else collapses
    to ``_``. Empty/missing → ``unknown``.
    """
    import re as _re
    if not s:
        return "unknown"
    out = _re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("._-")
    return out or "unknown"


def _default_target() -> str:
    """Sensible default when --target is not provided."""
    return "default-" + datetime.now().strftime("%Y%m%d")


def _resolve_run_dir(target: str, llm_slug: str, tier: str,
                     scenario_id: str, period: str) -> Path:
    """Build the run-output directory under EXP_ROOT.

    Layout:
        exp/<target>/<llm-slug>/<tier>/<scenario-id>/<period>/

    Collision policy: if the period dir already exists, append a
    ``.YYYYMMDDTHHMMSS`` suffix. This preserves prior data and the
    natural ordering (lexical sort = chronological order).

    Concurrency: `mkdir(exist_ok=False)` *is* the test — checking `.exists()`
    first would be a TOCTOU race, and two sweep workers starting the same
    (scenario, period) in the same second would also collide on an identical
    timestamp suffix. Both windows are closed by letting mkdir arbitrate and
    retrying with a counter.
    """
    parent = EXP_ROOT / target / llm_slug / tier / scenario_id
    parent.mkdir(parents=True, exist_ok=True)

    try:
        target_dir = parent / period
        target_dir.mkdir(exist_ok=False)
        return target_dir
    except FileExistsError:
        pass

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    for n in range(10000):
        suffix = stamp if n == 0 else f"{stamp}.{n}"
        target_dir = parent / f"{period}.{suffix}"
        try:
            target_dir.mkdir(exist_ok=False)
            return target_dir
        except FileExistsError:
            continue
    raise RuntimeError(
        f"could not allocate a run dir under {parent} for period {period!r}")


def _append_index_row(target: str, row: dict) -> None:
    """Append one JSONL row to exp/<target>/_index.jsonl.

    Cheap cross-LLM grep target; doesn't replace the per-run meta.json,
    just complements it.
    """
    idx = EXP_ROOT / target / "_index.jsonl"
    idx.parent.mkdir(parents=True, exist_ok=True)
    with idx.open("a") as f:
        f.write(json.dumps(row) + "\n")

# Agents live under repo/agents/<name>. Set PYTHONPATH so subprocess can
# import any of them by name. Each agent dir's pyproject expects its package
# to be importable as `<name>` (or via its own `setup.py develop`).
AGENTS_ROOT = REPO / "agents"


def _default_agent_pythonpath() -> list[str]:
    """Make every agent under agents/<name>/ importable."""
    out = [str(REPO / "evsandbox"), str(REPO)]
    if AGENTS_ROOT.is_dir():
        for d in AGENTS_ROOT.iterdir():
            if d.is_dir() and (d / d.name).is_dir():
                out.append(str(d))                                    # /repo/agents/<name>
    return out


# ---------------------------------------------------------------------------
# LM rate limiter
# ---------------------------------------------------------------------------

class LMRateLimiter:
    """In-flight semaphore + 60s rolling-window RPM cap.

    Note: this is process-global. Since the runner spawns agent subprocesses,
    only the subprocess invocations are throttled here — the agent itself
    may issue multiple LM calls before returning; the cap applies per agent
    run, not per LM call. If finer control is needed, the agent should
    self-throttle.
    """
    def __init__(self, rpm: int = 600, max_in_flight: int = 32):
        if rpm < 1 or max_in_flight < 1:
            raise ValueError("rpm and max_in_flight must be >= 1")
        self._rpm = rpm
        self._sem = threading.Semaphore(max_in_flight)
        self._tokens: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()

    @contextmanager
    def slot(self):
        self._sem.acquire()
        try:
            self._wait_for_token()
            yield
        finally:
            self._sem.release()

    def _wait_for_token(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._tokens and now - self._tokens[0] > 60.0:
                    self._tokens.popleft()
                if len(self._tokens) < self._rpm:
                    self._tokens.append(now)
                    return
                sleep_s = 60.0 - (now - self._tokens[0]) + 0.01
            time.sleep(max(0.01, sleep_s))


# ---------------------------------------------------------------------------
# Task / outcome
# ---------------------------------------------------------------------------

def _default_agent_cmd() -> str:
    """Use the parent's interpreter explicitly. Subprocess PATH is
    restricted, so a bare 'python' may resolve to the wrong binary."""
    return f"{sys.executable} -m smolagents_agent.worker"


@dataclass(frozen=True)
class RunTask:
    scenario_dir: Path
    period: str
    strategy: str = "pass_through"
    seed: int = 0
    agent_cmd: str = field(default_factory=_default_agent_cmd)
    agent_args: dict = field(default_factory=dict)
    score: bool = True
    timeout_s: int = 300
    target: str = field(default_factory=_default_target)
    judge: Optional[Judge] = None
    isolation: str = "none"


@dataclass
class RunOutcome:
    run_id: str
    run_dir: Path
    status: str
    wall_ms: int
    error_preview: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk_run_id(scenario_id: str, period: str) -> str:
    return f"{scenario_id}__{period}__{uuid.uuid4().hex[:8]}"


def scenario_opts_into_web_search(scenario) -> bool:
    """Web-search is scenario-driven via question_tags or scenario_id.

    The env makes this determination itself rather than asking the agent —
    so it can prep audit paths and env vars before spawning the agent.
    """
    tags = list(getattr(scenario, "question_tags", []) or [])
    if "requires_web_search" in tags:
        return True
    sid = getattr(scenario, "scenario_id", "") or ""
    return sid == "iata_air_passenger_monthly_analytical"


def _agent_env(world_root: Path, period: str, scenario, run_id: str,
               run_dir: Path,
               audit_path: Optional[Path]) -> dict[str, str]:
    """Restricted env for the agent subprocess."""
    env = {
        "PATH":         os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME":         str(world_root.parent),
        "PYTHONPATH":   os.pathsep.join(_default_agent_pythonpath()),
        ENV_CUTOFF:     period,
        ENV_RUN_ID:     run_id,
        # Streaming trace path. Agents that support streaming (e.g.
        # smolagents_agent via step_callback) append one JSONL row per
        # step here, so a partial trace survives even when the subprocess
        # is SIGKILLed at timeout. Single-shot agents may ignore this.
        ENV_TRACE_PATH: str(run_dir / "trace.jsonl"),
    }
    if "ANTHROPIC_API_KEY" in os.environ:
        env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    # OpenAI-compatible / self-hosted (vLLM) backend passthroughs. The agent
    # forms its own client; we just need to forward the URL/key and any
    # proxy config required by the host's VPN setup.
    for k in ("SELF_HOSTED_BASE_URL", "SELF_HOSTED_API_KEY", "OPENAI_API_KEY",
              "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL",
              "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
              "https_proxy", "http_proxy", "no_proxy"):
        if k in os.environ:
            env[k] = os.environ[k]
    if scenario_opts_into_web_search(scenario):
        if "TIMESAGE_SEARXNG" in os.environ:
            env[ENV_SEARXNG] = os.environ["TIMESAGE_SEARXNG"]
        if audit_path is not None:
            env[ENV_AUDIT_PATH] = str(audit_path)
    return env


def _read_line_until_deadline(stream, deadline: float) -> Optional[str]:
    """Block on a single stdout line from a subprocess, respecting a wall
    deadline (monotonic). Returns the line (with trailing newline) on
    success, None on timeout or EOF."""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        ready, _, _ = _select.select([stream], [], [], remaining)
        if not ready:
            return None
        line = stream.readline()
        if line == "":
            return None
        if line.strip():
            return line
        # Empty (whitespace-only) line: keep waiting — worker may have
        # printed a stray newline. Loop again with remaining budget.


def _audit_leakage_check(audit_path: Optional[Path], period: str) -> bool:
    if audit_path is None or not audit_path.exists():
        return False
    from .network import _cdx_cutoff_yyyymmdd                          # noqa: WPS433
    cap = _cdx_cutoff_yyyymmdd(period)
    for raw in audit_path.read_text().splitlines():
        try:
            row = json.loads(raw)
        except Exception:                                              # noqa: BLE001
            continue
        for ts in (row.get("archived_timestamps") or []):
            if ts[:8] > cap:
                return True
    return False


# ---------------------------------------------------------------------------
# Agent invocation
# ---------------------------------------------------------------------------

def _invoke_agent(world, scenario, scenario_dir, period,
                  prompt, audit_path, run_id, run_dir,
                  agent_cmd: str, agent_args: dict,
                  timeout_s: int,
                  isolation: str = "none"):
    env = _agent_env(world.root, period, scenario, run_id, run_dir, audit_path)
    req = {
        "scenario_dir": str(scenario_dir),
        "period":       period,
        "prompt":       prompt,
        "agent_args":   agent_args,
    }
    cmd = shlex.split(agent_cmd)
    if isolation == "bwrap":
        cmd, env = bwrap_command(cmd, env, world_root=world.root, run_dir=run_dir)
    t0 = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=str(world.root),
        env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    try:
        out, err = proc.communicate(input=json.dumps(req) + "\n",
                                    timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        (run_dir / "stderr.log").write_text(err or "")
        return {}, "", [], int((time.time() - t0) * 1000), STATUS_TIMEOUT

    wall_ms = int((time.time() - t0) * 1000)
    (run_dir / "stderr.log").write_text(err or "")

    if proc.returncode != 0 or not out.strip():
        # A crashing worker usually still emits a JSON envelope carrying its
        # own traceback. Preserve it — otherwise the run is recorded as
        # "agent_crash" with an empty stderr.log and nothing to debug from.
        (run_dir / "stderr.log").write_text(
            (err or "")
            + f"\n[parent] child exited rc={proc.returncode}\n"
            + f"[parent] child stdout:\n{out[:4000]}\n")
        return ({}, "", [], wall_ms,
                STATUS_AGENT_CRASH if proc.returncode else STATUS_INCOMPLETE)

    try:
        resp = json.loads(out.strip().splitlines()[-1])
    except Exception as exc:                                          # noqa: BLE001
        (run_dir / "stderr.log").write_text(
            (err or "") + f"\n[parent] could not parse child stdout: {exc!r}\n"
            + out[:2000])
        return {}, "", [], wall_ms, STATUS_AGENT_CRASH

    structured = resp.get("structured_answer") or {}
    # Report is a regular property in answer_schema (annotated `question_tag: "report"`).
    # Read it from structured_answer; fall back to a top-level `report` key for
    # backwards-compatible agents.
    report_val = structured.get("report") if isinstance(structured, dict) else None
    if not report_val:
        report_val = resp.get("report") or ""
    return (structured,
            report_val,
            resp.get("trace") or [],
            wall_ms,
            resp.get("status") or STATUS_OK)


# ---------------------------------------------------------------------------
# Single-run orchestration
# ---------------------------------------------------------------------------

def run_one(scenario_dir: Path,
            period: str,
            *,
            strategy: str = "pass_through",
            seed: int = 0,
            agent_cmd: Optional[str] = None,
            agent_args: Optional[dict] = None,
            score: bool = True,
            timeout_s: int = 300,
            target: Optional[str] = None,
            judge: Optional[Judge] = None,
            isolation: str = "none") -> dict:
    """Run one (scenario, period) end-to-end with the given agent.

    `isolation` is "none" (plain subprocess, cwd = sandbox) or "bwrap"
    (see evsandbox.isolation: the agent sees only the sandbox and code).

    Output dir: exp/<target>/<llm-slug>/<tier>/<scenario-id>/<period>/.
    `target` defaults to ``default-<YYYYMMDD>`` when not provided. The
    `llm-slug` is derived from ``agent_args.lm_model`` (sanitized).
    """
    agent_args = dict(agent_args or {})
    agent_cmd = agent_cmd or _default_agent_cmd()
    target = target or _default_target()

    scenario = load_scenario(scenario_dir)
    llm_slug = _slugify_llm(agent_args.get("lm_model") or "unknown")
    run_dir = _resolve_run_dir(target, llm_slug, scenario.tier,
                               scenario.scenario_id, period)
    run_id = _mk_run_id(scenario_dir.name, period)   # short uuid for env+logs

    full_prompt, rephrased = task_prompt(scenario, scenario_dir, period,
                                         strategy=strategy, seed=seed)

    # Audit path is set whenever the scenario opts into web search. The agent
    # is free to ignore it; the env will still post-audit if a file appears.
    audit_path: Optional[Path] = None
    if scenario_opts_into_web_search(scenario):
        audit_path = run_dir / "network_audit.jsonl"

    with build_world(scenario_dir, period, run_id=run_id) as world:
        structured, report, trace, wall_ms, status = _invoke_agent(
            world, scenario, scenario_dir, period,
            full_prompt, audit_path, run_id, run_dir,
            agent_cmd, agent_args, timeout_s,
            isolation=isolation,
        )

        # Trace policy:
        #   1. If a streaming agent already populated trace.jsonl (file
        #      exists AND non-empty), trust the streamed file — it has
        #      richer rows (worker_start, phase markers) that the
        #      stdout-returned trace lacks.
        #   2. Otherwise, write whatever stdout trace the worker returned
        #      (single-shot agents that only return it on stdout).
        #   3. If neither, ensure the file exists so downstream readers
        #      can stat it.
        trace_path = run_dir / "trace.jsonl"
        if trace_path.exists() and trace_path.stat().st_size > 0:
            pass  # streamed file wins
        elif trace:
            trace_path.write_text(
                "\n".join(json.dumps(e) for e in trace) + "\n"
            )
        else:
            trace_path.write_text("")
        (run_dir / "world_snapshot.json").write_text(
            json.dumps({"files": world.files}, indent=2)
        )

        # On non-OK status, copy the sandbox into the run dir for debugging.
        # We do this INSIDE the context manager so `world.base` still exists.
        if status != STATUS_OK:
            sandbox_dst = run_dir / "sandbox"
            if sandbox_dst.exists():
                shutil.rmtree(sandbox_dst, ignore_errors=True)
            try:
                shutil.copytree(world.base, sandbox_dst)
            except Exception:                                          # noqa: BLE001
                pass  # debug aid only; never let copy failure mask the real status

    if _audit_leakage_check(audit_path, period):
        status = STATUS_LEAKAGE

    run_record = {
        "run_id":            run_id,
        "scenario_id":       scenario.scenario_id,
        "tier":              scenario.tier,
        "period":            period,
        "agent_meta": {
            "agent_cmd": agent_cmd,
            "agent_args": agent_args,
            "framework": "evsandbox",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "structured_answer": structured,
        # Top-level copy only when the agent left `report` out of its answer.
        **({} if "report" in structured else {"report": report}),
    }
    (run_dir / "run_record.json").write_text(json.dumps(run_record, indent=2))

    meta = {
        "run_id":             run_id,
        "target":             target,
        "llm_slug":           llm_slug,
        "scenario_id":        scenario.scenario_id,
        "period":             period,
        "tier":               scenario.tier,
        "agent_cmd":          agent_cmd,
        "agent_args":         agent_args,
        "isolation":          isolation,
        "strategy":           rephrased.strategy,
        "keypoint_preserved": rephrased.keypoint_count_preserved,
        "seed":               seed,
        "wall_ms":            wall_ms,
        "status":             status,
        "n_trace_entries":    len(trace),
        "leakage_suspected":  status == STATUS_LEAKAGE,
        "started_at":         datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    if score and status in {STATUS_OK, STATUS_INCOMPLETE}:
        from evbench.evaluator.schemas import RunRecord as RR
        judge_obj = judge if judge is not None else Judge(mock=True)
        rec = _scoresuite_score_one(
            scenario_dir, period, RR(**run_record), judge_obj)
        (run_dir / "score_record.json").write_text(rec.model_dump_json(indent=2))

    _append_index_row(target, {
        "run_id":      run_id,
        "llm_slug":    llm_slug,
        "tier":        scenario.tier,
        "scenario_id": scenario.scenario_id,
        "period":      period,
        "status":      status,
        "wall_ms":     wall_ms,
        "run_dir":     str(run_dir.relative_to(EXP_ROOT.parent)),
        "started_at":  meta["started_at"],
    })

    return {"run_dir": str(run_dir), "run_id": run_id,
            "status": status, "wall_ms": wall_ms}


# ---------------------------------------------------------------------------
# Concurrent sweep
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Episode mode: periods of one scenario, played chronologically, with
# scored feedback from each turn fed into the next turn's request.
# ---------------------------------------------------------------------------

def _list_periods(scenario_dir: Path) -> list[str]:
    inst = scenario_dir / "instances"
    if not inst.is_dir():
        return []
    return sorted(p.name for p in inst.iterdir() if p.is_dir())


def run_episode(scenario_dir: Path, *,
                periods: Optional[list[str]] = None,
                strategy: str = "pass_through",
                seed: int = 0,
                agent_cmd: Optional[str] = None,
                agent_args: Optional[dict] = None,
                timeout_s: int = 300,
                feedback_mode: FeedbackMode = "score",
                on_turn: Optional[Callable[[dict], None]] = None,
                target: Optional[str] = None,
                judge: Optional[Judge] = None,
                isolation: str = "none",
                ) -> dict:
    """Run all periods of one scenario in a SINGLE continuous conversation.

    The agent subprocess is spawned once and re-used across all periods.
    Memory accumulates naturally (smolagents `agent.run(reset=False)`),
    so period N's LLM call sees periods 0..N-1's conversation as context.

    Before each period's message the runner refreshes the sandbox in place
    (evbench.engine.refresh_world), so the agent sees that period's CSV and
    gt_source/; files the agent wrote there itself are kept. A worker may
    write a `memory_after_<period>.json` snapshot to its episode directory
    after each period, for offline resumption (timesage_agent always does;
    smolagents_agent with agent_args memory_snapshots=true).

    Under isolation="bwrap" the worker's episode directory is
    `<episode>/agent/`, mounted at /out: the episode directory itself also
    receives score records, which carry past periods' ground truth.

    Layout (one episode = one directory):
        exp/<target>/<llm>/<tier>/<scenario>/
        ├── episode_meta.json
        ├── trace.jsonl
        ├── memory_after_<period>.json   (if the worker keeps snapshots)
        └── instances/<period>/
            ├── answer.json
            ├── report.md
            ├── meta.json
            └── score_record.json

    Between periods, the runner scores period N's submission and prepends
    a markdown feedback block (per-keypoint accuracy vs ground truth, plus
    judge-evaluated dimensions) to period N+1's prompt before forwarding
    it to the worker. `feedback_mode` controls the depth:
      * "none"     — skip the feedback block entirely
      * "score"    — keypoint pass/fail + GT values + judge axis scores
      * "detailed" — also include judge atomic-fact verdicts + rationale
    The agent's conversation memory naturally absorbs the feedback as
    part of the next user turn.
    """
    if periods is None:
        periods = _list_periods(scenario_dir)
    if not periods:
        return {"scenario_dir": str(scenario_dir), "periods": [],
                "turns": []}

    agent_args = dict(agent_args or {})
    agent_cmd = agent_cmd or _default_agent_cmd()
    target = target or _default_target()

    scenario = load_scenario(scenario_dir)

    llm_slug = _slugify_llm(agent_args.get("lm_model") or "unknown")
    # Episode dir is one level shallower than single-run mode — no per-period
    # subdir. _resolve_run_dir's collision policy applies to the scenario
    # dir itself: re-running the same (target, llm, scenario) timestamps,
    # UNLESS env TIMESAGE_RESUME=1 is set — then we reuse the existing
    # episode_dir so the worker's resume logic can pick up where it left
    # off (skip done periods + load memory carry).
    episode_root = EXP_ROOT / target / llm_slug / scenario.tier
    episode_root.mkdir(parents=True, exist_ok=True)
    episode_dir = episode_root / scenario.scenario_id
    if episode_dir.exists() and os.environ.get("TIMESAGE_RESUME") == "1":
        pass       # reuse — worker handles the partial-state logic
    else:
        # Same TOCTOU reasoning as _resolve_run_dir: mkdir arbitrates.
        try:
            episode_dir.mkdir(exist_ok=False)
        except FileExistsError:
            stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            for n in range(10000):
                suffix = stamp if n == 0 else f"{stamp}.{n}"
                episode_dir = episode_root / f"{scenario.scenario_id}.{suffix}"
                try:
                    episode_dir.mkdir(exist_ok=False)
                    break
                except FileExistsError:
                    continue
            else:
                raise RuntimeError(
                    f"could not allocate an episode dir under {episode_root}")

    run_id = _mk_run_id(scenario_dir.name, periods[0])
    instances_root = episode_dir / "instances"
    instances_root.mkdir(parents=True, exist_ok=True)

    # What the worker may write to. Under bwrap it must not see the score
    # records the runner writes into episode_dir, so it gets a subdir.
    agent_dir = episode_dir / "agent" if isolation == "bwrap" else episode_dir
    agent_dir.mkdir(exist_ok=True)

    # Audit path enabled when the scenario opts into web search.
    audit_path: Optional[Path] = None
    if scenario_opts_into_web_search(scenario):
        audit_path = agent_dir / "network_audit.jsonl"

    # Interactive episode loop:
    #   1. parent sends a setup message (scenario_dir + agent_args + episode meta);
    #   2. for each period, parent refreshes the sandbox to that period, sends
    #      {period, cutoff, prompt} on stdin and reads one response line; parent scores the period and prepends the markdown
    #      feedback to the NEXT period's prompt;
    #   3. parent sends {"done": true} and waits for the worker's final summary.
    # The worker keeps a single CodeAgent alive across all periods so memory
    # accumulates naturally (smolagents `agent.run(reset=False)`).
    from evbench.evaluator.schemas import RunRecord as RR               # noqa: WPS433
    judge_obj = judge if judge is not None else Judge(mock=True)
    turns: list[dict] = []
    parse_err: Optional[str] = None
    sandbox_err: Optional[str] = None
    timed_out = False
    timed_out_period: Optional[str] = None

    with build_world(scenario_dir, periods[0], run_id=run_id) as world:
        # Env is fixed at spawn, so it carries the FIRST period's cutoff; each
        # period message then carries its own (protocol.apply_period_cutoff).
        env = _agent_env(world.root, periods[0], scenario, run_id,
                         agent_dir, audit_path)
        cmd = shlex.split(agent_cmd)
        if isolation == "bwrap":
            cmd, env = bwrap_command(cmd, env, world_root=world.root, run_dir=agent_dir)
        t0 = time.time()
        proc = subprocess.Popen(
            cmd, cwd=str(world.root), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )

        setup_msg = {
            "scenario_dir": str(scenario_dir),
            "agent_args":   agent_args,
            "episode": {
                "interactive": True,
                "episode_dir": OUT_DIR if isolation == "bwrap" else str(agent_dir),
                "periods":     periods,
            },
        }
        try:
            proc.stdin.write(json.dumps(setup_msg) + "\n")
            proc.stdin.flush()
        except BrokenPipeError:
            timed_out = True

        prev_feedback_md: str = ""
        for i, period in enumerate(periods):
            if proc.poll() is not None:
                # Worker died before we could send this period.
                break
            if i > 0:                       # build_world already did periods[0]
                try:
                    refresh_world(world, period)
                except Exception as exc:                                # noqa: BLE001
                    sandbox_err = f"{period}: {exc!r}"
                    break

            base_prompt = episode_prompt(
                scenario, scenario_dir, period,
                is_first=(i == 0), strategy=strategy, seed=seed,
            )
            full_prompt = (prev_feedback_md + "\n\n---\n\n" + base_prompt
                           if prev_feedback_md else base_prompt)

            try:
                proc.stdin.write(json.dumps({"period": period,
                                              "cutoff": period,
                                              "prompt": full_prompt}) + "\n")
                proc.stdin.flush()
            except BrokenPipeError:
                break
            # timeout_s is a per-period budget, restarted for every period.
            deadline = time.monotonic() + timeout_s

            resp_line = _read_line_until_deadline(proc.stdout, deadline)
            if resp_line is None:
                timed_out = True
                timed_out_period = period
                break
            try:
                period_resp = json.loads(resp_line)
            except Exception as exc:                                    # noqa: BLE001
                parse_err = f"per-period parse: {exc!r}"
                period_resp = {"period": period, "status": STATUS_AGENT_CRASH,
                               "wall_ms": 0, "structured_answer": {},
                               "report": ""}

            period_name = period_resp.get("period") or period
            structured  = period_resp.get("structured_answer") or {}
            report      = (structured.get("report") if isinstance(structured, dict) else None) \
                          or period_resp.get("report") or ""
            status      = period_resp.get("status") or STATUS_INCOMPLETE
            wall        = int(period_resp.get("wall_ms") or 0)

            # Per-period network-leakage check. The audit log accumulates
            # across the whole episode; we check whether any row has an
            # archived_timestamp > THIS period's cutoff. A single-period
            # run_one already does this (line 456); without the equivalent
            # here, leakage_detected status would NEVER fire in episode
            # mode even if the agent's web_search violated time isolation.
            if _audit_leakage_check(audit_path, period_name):
                status = STATUS_LEAKAGE

            pdir = instances_root / period_name
            pdir.mkdir(parents=True, exist_ok=True)
            rr_dict = {
                "run_id":      f"{run_id}__{period_name}",
                "scenario_id": scenario.scenario_id,
                "tier":        scenario.tier,
                "period":      period_name,
                "agent_meta": {
                    "agent_cmd": agent_cmd, "agent_args": agent_args,
                    "framework": "evsandbox", "episode_mode": "continuous",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                "structured_answer": structured,
                **({} if "report" in structured else {"report": report}),
            }
            (pdir / "run_record.json").write_text(json.dumps(rr_dict, indent=2))

            score_dict: dict = {}
            if status in {STATUS_OK, STATUS_INCOMPLETE}:
                try:
                    rec = _scoresuite_score_one(
                        scenario_dir, period_name, RR(**rr_dict), judge_obj)
                    (pdir / "score_record.json").write_text(
                        rec.model_dump_json(indent=2))
                    score_dict = json.loads(rec.model_dump_json())
                except Exception as exc:                                # noqa: BLE001
                    (pdir / "score_record.json").write_text(json.dumps(
                        {"error": f"scoring failed: {exc!r}"}, indent=2))
                    score_dict = {"error": f"scoring failed: {exc!r}"}

            # Build feedback for the NEXT period's prompt (skip on last).
            if i + 1 < len(periods):
                if score_dict and not score_dict.get("error") \
                        and feedback_mode != "none":
                    fb_turn = build_feedback(
                        period=period_name, run_record=rr_dict,
                        score_record=score_dict, scenario_dir=scenario_dir,
                        mode=feedback_mode,
                    )
                    prev_feedback_md = fb_turn.rendered
                elif score_dict.get("error"):
                    prev_feedback_md = render_scoring_unavailable(
                        period_name, score_dict["error"])
                else:
                    prev_feedback_md = ""

            turn = {"period": period_name, "status": status, "wall_ms": wall,
                    "turn": i + 1, "n_turns": len(periods),
                    "usage": period_resp.get("usage"),
                    "run_dir": str(pdir),
                    "structured_answer": structured,
                    "score": score_dict}
            turns.append(turn)
            _append_index_row(target, {
                "run_id":      f"{run_id}__{period_name}",
                "llm_slug":    llm_slug,
                "tier":        scenario.tier,
                "scenario_id": scenario.scenario_id,
                "period":      period_name,
                "status":      status,
                "wall_ms":     wall,
                "run_dir":     str(pdir.relative_to(EXP_ROOT.parent)),
                "started_at":  datetime.now(timezone.utc).isoformat(),
            })
            if on_turn is not None:
                on_turn(turn)

        # Tell the worker we're done; communicate() will close stdin and
        # drain stdout/stderr (don't close stdin manually — that breaks
        # the internal flush in CPython's subprocess._communicate).
        if proc.poll() is None:
            try:
                proc.stdin.write(json.dumps({"done": True}) + "\n")
                proc.stdin.flush()
            except BrokenPipeError:
                pass

        try:
            tail_out, err = proc.communicate(
                timeout=5.0 if timed_out else timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            tail_out, err = proc.communicate()
            timed_out = True

        (episode_dir / "stderr.log").write_text(err or "")
        (episode_dir / "world_snapshot.json").write_text(
            json.dumps({"files": world.files}, indent=2)
        )

        # On failure: copy the (last-period-materialised) sandbox in for debug.
        if proc.returncode != 0 or timed_out:
            sandbox_dst = episode_dir / "sandbox"
            if sandbox_dst.exists():
                shutil.rmtree(sandbox_dst, ignore_errors=True)
            try:
                shutil.copytree(world.base, sandbox_dst)
            except Exception:                                           # noqa: BLE001
                pass

    wall_ms_subproc = int((time.time() - t0) * 1000)

    # Episode-level meta.
    n_ok = sum(1 for t in turns if t.get("status") == STATUS_OK)
    # "ok" needs every requested period answered; a per-period timeout
    # leaves the rest unplayed, which is "partial".
    episode_status = "ok" if n_ok == len(periods) else \
                     ("partial" if turns else
                      ("timeout" if timed_out else STATUS_AGENT_CRASH))

    # Episode-level aggregate scores. One JSON the user/evaluator can `cat`
    # to see "how did the model do across all periods of this scenario?"
    # without grepping through instances/<period>/score_record.json one by one.
    n_scored = 0
    aggregate_sum = 0.0
    pass_count = 0
    axis_acc: dict[str, list[float]] = {}
    period_summaries: list[dict] = []
    for t in turns:
        sd = t.get("score") or {}
        if sd.get("error") or not sd:
            period_summaries.append({
                "period":            t["period"],
                "status":            t["status"],
                "wall_ms":           t["wall_ms"],
                "structured_answer": t.get("structured_answer") or {},
                "aggregate":         None,
                "passed":            False,
                "score_error":       sd.get("error") if isinstance(sd, dict) else None,
            })
            continue
        agg = sd.get("aggregate")
        passed = sd.get("passed")
        scores_block = sd.get("scores") or {}
        axes = {ax: (val.get("value") if isinstance(val, dict) else None)
                for ax, val in scores_block.items()}
        for ax, v in axes.items():
            if isinstance(v, (int, float)):
                axis_acc.setdefault(ax, []).append(float(v))
        if isinstance(agg, (int, float)):
            n_scored += 1
            aggregate_sum += float(agg)
        if passed:
            pass_count += 1
        # Extract per-keypoint detail so the aggregate file is self-contained
        # for debugging (agent_value vs gt_value mismatches).
        per_kp_blocks = {}
        kp_axis = scores_block.get("keypoint_accuracy", {})
        if isinstance(kp_axis, dict):
            detail = kp_axis.get("detail") or {}
            if isinstance(detail, dict):
                per_kp_blocks = detail.get("per_kp") or []
        period_summaries.append({
            "period":            t["period"],
            "status":            t["status"],
            "wall_ms":           t["wall_ms"],
            "structured_answer": t.get("structured_answer") or {},
            "aggregate":         agg,
            "passed":            bool(passed) if passed is not None else None,
            "axis_scores":       axes,
            "per_keypoint":      per_kp_blocks,
        })

    axis_means = {ax: round(sum(vs) / len(vs), 2)
                  for ax, vs in axis_acc.items() if vs}
    mean_aggregate = (round(aggregate_sum / n_scored, 2)
                      if n_scored else None)
    pass_rate = round(pass_count / len(turns), 3) if turns else None

    (episode_dir / "episode_scores.json").write_text(json.dumps({
        "scenario_id":      scenario.scenario_id,
        "tier":             scenario.tier,
        "target":           target,
        "llm_slug":         llm_slug,
        "n_periods":        len(periods),
        "n_completed":      len(turns),
        "n_ok":             n_ok,
        "n_scored":         n_scored,
        "mean_aggregate":   mean_aggregate,
        "pass_count":       pass_count,
        "pass_rate":        pass_rate,
        "axis_means":       axis_means,
        "periods":          period_summaries,
        "judge": {
            "backend": getattr(judge_obj, "backend", "mock"),
            "mock":    getattr(judge_obj, "backend", "mock") == "mock",
            "model":   getattr(judge_obj, "model", None),
            "quality_model": getattr(judge_obj, "quality_model", None),
            "thinking_budget":
                getattr(judge_obj, "thinking_budget", None)
                if getattr(judge_obj, "backend", "") == "claude_thinking" else None,
        },
    }, indent=2, ensure_ascii=False))

    (episode_dir / "episode_meta.json").write_text(json.dumps({
        "run_id":        run_id,
        "target":        target,
        "llm_slug":      llm_slug,
        "scenario_id":   scenario.scenario_id,
        "tier":          scenario.tier,
        "periods":       periods,
        "periods_completed": [t["period"] for t in turns],
        "n_ok":          n_ok,
        "n_total":       len(periods),
        "status":        episode_status,
        "wall_ms":       wall_ms_subproc,
        "subproc_return_code": proc.returncode,
        "subproc_timed_out":   timed_out,
        "timed_out_period":    timed_out_period,
        "subproc_parse_error": parse_err,
        "sandbox_error":       sandbox_err,
        "isolation":           isolation,
        "agent_cmd":     agent_cmd,
        "agent_args":    agent_args,
        "started_at":    datetime.now(timezone.utc).isoformat(),
    }, indent=2, default=str))

    return {
        "scenario_dir": str(scenario_dir),
        "episode_dir":  str(episode_dir),
        "periods":      periods,
        "turns":        turns,
        "status":       episode_status,
        "n_ok":         n_ok,
        "n_total":      len(periods),
    }


@dataclass(frozen=True)
class EpisodeTask:
    scenario_dir: Path
    periods: Optional[list[str]] = None
    strategy: str = "pass_through"
    seed: int = 0
    agent_cmd: str = field(default_factory=_default_agent_cmd)
    agent_args: dict = field(default_factory=dict)
    timeout_s: int = 300
    feedback_mode: FeedbackMode = "score"
    target: str = field(default_factory=_default_target)
    judge: Optional[Judge] = None
    isolation: str = "none"


def sweep_episodes(tasks: Iterable[EpisodeTask], *,
                   concurrency: int = 32,
                   rpm_cap: int = 600,
                   on_progress: Optional[Callable[[str, dict], None]] = None,
                   ) -> list[dict]:
    """Run multiple episodes in parallel.

    Each episode runs sequentially internally (period N waits for N-1's
    score). Across episodes (i.e. across scenarios), full parallelism. With
    32 worker threads and ~17 scenarios, all episodes run concurrently and
    wall-clock = max(episode duration).
    """
    task_list = list(tasks)
    if not task_list:
        return []

    limiter = LMRateLimiter(rpm=rpm_cap, max_in_flight=concurrency)
    results: list[dict] = []
    res_lock = threading.Lock()

    def _do(task: EpisodeTask) -> dict:
        with limiter.slot():
            try:
                ep = run_episode(
                    task.scenario_dir,
                    periods=task.periods,
                    strategy=task.strategy, seed=task.seed,
                    agent_cmd=task.agent_cmd, agent_args=task.agent_args,
                    timeout_s=task.timeout_s,
                    feedback_mode=task.feedback_mode,
                    target=task.target,
                    judge=task.judge,
                    isolation=task.isolation,
                    on_turn=lambda turn: (on_progress(task.scenario_dir.name, turn)
                                           if on_progress else None),
                )
                ep["status"] = "ok"
                return ep
            except Exception as exc:                                  # noqa: BLE001
                return {"scenario_dir": str(task.scenario_dir),
                        "status": STATUS_AGENT_CRASH,
                        "error_preview": repr(exc)[:300]}

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(_do, t) for t in task_list]
        try:
            for fut in as_completed(futs):
                ep = fut.result()
                with res_lock:
                    results.append(ep)
        except KeyboardInterrupt:
            for f in futs:
                f.cancel()
            raise
    return results


# ---------------------------------------------------------------------------
# Independent sweep (legacy — no feedback between turns)
# ---------------------------------------------------------------------------

def sweep(tasks: Iterable[RunTask], *,
          concurrency: int = 32,
          rpm_cap: int = 600,
          on_progress: Optional[Callable[[RunOutcome], None]] = None,
          ) -> list[RunOutcome]:
    task_list = list(tasks)
    if not task_list:
        return []

    limiter = LMRateLimiter(rpm=rpm_cap, max_in_flight=concurrency)
    outcomes: list[RunOutcome] = []
    out_lock = threading.Lock()

    def _do(task: RunTask) -> RunOutcome:
        with limiter.slot():
            try:
                rec = run_one(
                    task.scenario_dir, task.period,
                    strategy=task.strategy, seed=task.seed,
                    agent_cmd=task.agent_cmd,
                    agent_args=task.agent_args,
                    score=task.score,
                    timeout_s=task.timeout_s,
                    target=task.target,
                    judge=task.judge,
                    isolation=task.isolation,
                )
                return RunOutcome(run_id=rec["run_id"],
                                  run_dir=Path(rec["run_dir"]),
                                  status=rec["status"],
                                  wall_ms=rec["wall_ms"])
            except Exception as exc:                                  # noqa: BLE001
                return RunOutcome(run_id="?", run_dir=Path("/dev/null"),
                                  status=STATUS_AGENT_CRASH, wall_ms=0,
                                  error_preview=repr(exc)[:300])

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = [ex.submit(_do, t) for t in task_list]
        try:
            for fut in as_completed(futs):
                o = fut.result()
                with out_lock:
                    outcomes.append(o)
                if on_progress is not None:
                    on_progress(o)
        except KeyboardInterrupt:
            for f in futs:
                f.cancel()
            raise
    return outcomes
