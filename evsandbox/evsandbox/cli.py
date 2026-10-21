"""evsandbox CLI:

  evsandbox run <scenario_dir> <period> [--agent-cmd "..."] [--strategy ...] [--isolation bwrap]
  evsandbox sweep [--tier ...] [--concurrency 32] [--rpm-cap 600] [--agent-cmd "..."] [--isolation bwrap]
  evsandbox e2e-sample
  evsandbox report <run_id>
  evsandbox gc [--older-than 24h]
  evsandbox searxng up | down | healthcheck

The agent is selected via --agent-cmd. Aliases (see AGENT_ALIASES) make
common choices terse:
    --agent smolagents_agent       → "python -m smolagents_agent.worker"

Agent-specific knobs (LM model, seed, etc.) go through repeated
--agent-arg key=value flags. The runner does not interpret them; they pass
through verbatim in the AgentRequest.agent_args JSON object.

`--config exp.yaml` sets any of these from an experiment file (see
evsandbox/config.py); flags given on the command line still win. The
settings a command actually ran with are written to exp/<target>/config.json.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import load_config
from .term import episode_summary, turn_line
from .runner import (
    EXP_ROOT, RUNS_ROOT, EpisodeTask, RunTask, _default_target,
    run_episode, run_one, sweep, sweep_episodes,
)


REPO = Path(__file__).resolve().parents[2]

SAMPLED = [
    (REPO / "evbench/scenarios/easy/climate/noaa_cpc_ao_monthly_phase",                  "2024-05"),
    (REPO / "scenarios_unfinished/middle/agriculture/usda_crop_progress_weekly_brief",    "2024-wk20"),
    (REPO / "scenarios_unfinished/hard/transportation/iata_air_passenger_monthly_analytical", "2024-04"),
]

SEARXNG_COMPOSE = REPO / "evsandbox" / "deploy" / "searxng" / "docker-compose.yml"

AGENT_ALIASES = {
    "smolagents_agent":  f"{sys.executable} -m smolagents_agent.worker",
    "timesage_agent":    f"{sys.executable} -m timesage_agent.worker",
}


def _resolve_agent_cmd(agent: str | None, agent_cmd: str | None) -> str:
    """Resolve the agent command. Substitutes the parent's sys.executable
    for a bare leading 'python' so subprocesses don't accidentally pick up
    a different interpreter from the restricted PATH.
    """
    if agent_cmd:
        if agent_cmd.startswith("python "):
            return sys.executable + agent_cmd[len("python"):]
        return agent_cmd
    if agent:
        if agent in AGENT_ALIASES:
            return AGENT_ALIASES[agent]
        return f"{sys.executable} -m {agent}.worker"
    return AGENT_ALIASES["smolagents_agent"]


def _build_judge(args):
    """Judge from the --judge* flags (or their config-file values)."""
    from evbench.evaluator.judge import build_judge
    return build_judge(args.judge, args.judge_model,
                       args.judge_quality_model, args.judge_thinking,
                       args.judge_max_tokens, args.judge_extra_body,
                       args.judge_by_kind, args.judge_base_url)


def _agent_args(args) -> dict:
    """The config file's agent.args, overlaid with --agent-arg pairs."""
    out = dict(getattr(args, "config_agent_args", None) or {})
    out.update(_parse_agent_args(args.agent_arg))
    return out


#: Settings recorded in exp/<target>/config.json, when the command has them.
_RECORDED = ("scenario_dir", "period", "periods", "tier", "mode", "strategy",
             "strategies", "seed", "timeout", "isolation", "feedback_mode",
             "concurrency", "rpm_cap", "max_tasks")


def _record_config(args, agent_cmd: str, agent_args: dict, judge) -> None:
    """Write the settings this command actually runs with to exp/<target>/.

    A later command with different settings under the same target gets its
    own timestamped file instead of overwriting the first.
    """
    rec = {"command": args.cmd,
           "config_file": str(Path(args.config).resolve()) if args.config else None,
           "agent_cmd": agent_cmd, "agent_args": agent_args,
           "judge": judge.describe(),
           **{k: getattr(args, k) for k in _RECORDED if hasattr(args, k)}}
    out_dir = EXP_ROOT / args.target
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "config.json"
    text = json.dumps(rec, indent=2, default=str) + "\n"
    if path.exists() and path.read_text() != text:
        path = out_dir / f"config.{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
        print(f"note: {args.target} already has a different config.json; "
              f"writing {path.name}", file=sys.stderr)
    path.write_text(text)


def _parse_agent_args(pairs: list[str]) -> dict:
    out: dict = {}
    for kv in pairs or []:
        if "=" not in kv:
            raise SystemExit(f"--agent-arg must be key=value, got: {kv!r}")
        k, v = kv.split("=", 1)
        # Best-effort type coercion: int / float / json / fallback to str.
        try:
            out[k] = json.loads(v)
            continue
        except Exception:                                              # noqa: BLE001
            pass
        out[k] = v
    return out


# ---------------------------- single runs ---------------------------------

def _require_scenario(scenario_dir: str) -> None:
    """A mistyped path would otherwise run nothing and report success."""
    if not (Path(scenario_dir) / "instances").is_dir():
        raise SystemExit(f"not a scenario directory (no instances/): {scenario_dir}")


def cmd_run(args):
    _require_scenario(args.scenario_dir)
    agent_cmd = _resolve_agent_cmd(args.agent, args.agent_cmd)
    agent_args = _agent_args(args)
    judge = _build_judge(args)
    _record_config(args, agent_cmd, agent_args, judge)
    out = run_one(
        Path(args.scenario_dir).resolve(), args.period,
        strategy=args.strategy, seed=args.seed,
        agent_cmd=agent_cmd,
        agent_args=agent_args,
        score=not args.no_score,
        timeout_s=args.timeout,
        target=args.target,
        judge=judge,
        isolation=args.isolation,
    )
    print(json.dumps(out, indent=2))
    return 0


def cmd_episode(args):
    _require_scenario(args.scenario_dir)
    agent_cmd = _resolve_agent_cmd(args.agent, args.agent_cmd)
    agent_args = _agent_args(args)
    judge = _build_judge(args)
    _record_config(args, agent_cmd, agent_args, judge)
    periods = [p.strip() for p in args.periods.split(",")] if args.periods else None

    def _on_turn(rec):
        print("  " + turn_line(rec), flush=True)

    result = run_episode(
        Path(args.scenario_dir).resolve(),
        periods=periods,
        strategy=args.strategy, seed=args.seed,
        agent_cmd=agent_cmd, agent_args=agent_args,
        timeout_s=args.timeout,
        feedback_mode=args.feedback_mode,
        target=args.target,
        judge=judge,
        on_turn=_on_turn,
        isolation=args.isolation,
    )
    print("\n" + episode_summary(result["turns"]))
    return 0


def cmd_e2e_sample(args):
    agent_cmd = _resolve_agent_cmd(args.agent, args.agent_cmd)
    agent_args = _agent_args(args)
    target = args.target or None
    tasks = [RunTask(scenario_dir=s, period=p,
                     strategy=args.strategy, seed=args.seed,
                     agent_cmd=agent_cmd, agent_args=agent_args,
                     timeout_s=args.timeout,
                     **({"target": target} if target else {}))
             for s, p in SAMPLED]
    if args.concurrency <= 1:
        results = [run_one(t.scenario_dir, t.period,
                           strategy=t.strategy, seed=t.seed,
                           agent_cmd=t.agent_cmd, agent_args=t.agent_args,
                           score=t.score, timeout_s=t.timeout_s,
                           target=t.target) for t in tasks]
        run_dirs = [Path(r["run_dir"]) for r in results]
    else:
        outcomes = sweep(tasks, concurrency=args.concurrency,
                         rpm_cap=args.rpm_cap,
                         on_progress=lambda o: print(
                             f"  [{o.status:>16s}] {o.run_id}  wall={o.wall_ms}ms"))
        run_dirs = [o.run_dir for o in outcomes]

    print("\nScore summary:")
    for d in run_dirs:
        sp = d / "score_record.json"
        if not sp.exists():
            print(f"  {d.name:60s}  (no score record)")
            continue
        rec = json.loads(sp.read_text())
        print(f"  {rec['scenario_id']:48s} "
              f"aggregate={rec.get('aggregate')!s:>8}  "
              f"passed={rec.get('passed')}")
    return 0


# ---------------------------- sweep -----------------------------------------

def _enumerate_scenarios(tier: str | None):
    scenarios_root = REPO / "evbench" / "scenarios"
    for tier_dir in sorted(scenarios_root.iterdir()):
        if not tier_dir.is_dir():
            continue
        if tier and tier_dir.name != tier:
            continue
        for domain_dir in sorted(tier_dir.iterdir()):
            if not domain_dir.is_dir():
                continue
            for scen_dir in sorted(domain_dir.iterdir()):
                if (scen_dir / "instances").is_dir():
                    yield scen_dir


def _cmd_sweep_episode(args, agent_cmd, agent_args, judge):
    target = args.target or None
    extra = {"target": target} if target else {}
    tasks: list[EpisodeTask] = []
    for scen_dir in _enumerate_scenarios(args.tier):
        for strategy in args.strategies.split(","):
            tasks.append(EpisodeTask(
                scenario_dir=scen_dir.resolve(),
                strategy=strategy.strip(),
                seed=args.seed,
                agent_cmd=agent_cmd, agent_args=agent_args,
                timeout_s=args.timeout,
                feedback_mode=args.feedback_mode,
                judge=judge,
                isolation=args.isolation,
                **extra,
            ))
    if args.max_tasks:
        tasks = tasks[: args.max_tasks]
    print(f"sweep[episode]: {len(tasks)} episodes, concurrency={args.concurrency}, "
          f"rpm_cap={args.rpm_cap}, feedback_mode={args.feedback_mode}, "
          f"agent_cmd={agent_cmd!r}")
    t0 = time.time()
    completed: dict[str, int] = {"n": 0}

    def _progress(scenario_name, turn_rec):
        # Per-turn progress; episode-level progress is implicit in completion count
        print(f"  [{scenario_name}] " + turn_line(turn_rec), flush=True)

    results = sweep_episodes(tasks, concurrency=args.concurrency,
                             rpm_cap=args.rpm_cap, on_progress=_progress)
    total_ms = int((time.time() - t0) * 1000)
    summary = {
        "mode":     "episode",
        "episodes": len(results),
        "ok":       sum(1 for r in results if r.get("status") == "ok"),
        "crash":    sum(1 for r in results if r.get("status") == "agent_crash"),
        "wall_ms":  total_ms,
    }
    print("\nsweep complete:", json.dumps(summary, indent=2))
    return 0 if summary["crash"] == 0 else 1


def cmd_sweep(args):
    agent_cmd = _resolve_agent_cmd(args.agent, args.agent_cmd)
    agent_args = _agent_args(args)
    judge = _build_judge(args)
    _record_config(args, agent_cmd, agent_args, judge)
    if args.mode == "episode":
        return _cmd_sweep_episode(args, agent_cmd, agent_args, judge)

    target = args.target or None
    extra = {"target": target} if target else {}
    tasks: list[RunTask] = []
    for scen_dir in _enumerate_scenarios(args.tier):
        inst_dir = scen_dir / "instances"
        for period_dir in sorted(inst_dir.iterdir()):
            if not period_dir.is_dir():
                continue
            for strategy in args.strategies.split(","):
                tasks.append(RunTask(
                    scenario_dir=scen_dir.resolve(),
                    period=period_dir.name,
                    strategy=strategy.strip(),
                    seed=args.seed,
                    agent_cmd=agent_cmd,
                    agent_args=agent_args,
                    timeout_s=args.timeout,
                    judge=judge,
                    isolation=args.isolation,
                    **extra,
                ))
    if args.max_tasks:
        tasks = tasks[: args.max_tasks]
    print(f"sweep[independent]: {len(tasks)} tasks, concurrency={args.concurrency}, "
          f"rpm_cap={args.rpm_cap}, agent_cmd={agent_cmd!r}")
    t0 = time.time()
    completed = 0

    def _progress(o):
        nonlocal completed
        completed += 1
        elapsed = time.time() - t0
        line = (f"  [{completed:4d}/{len(tasks)}] "
                f"[{o.status:>16s}] {o.run_id}  "
                f"wall={o.wall_ms}ms elapsed={elapsed:.1f}s")
        if o.error_preview:
            line += f"  err={o.error_preview}"
        print(line, flush=True)

    outcomes = sweep(tasks, concurrency=args.concurrency,
                     rpm_cap=args.rpm_cap, on_progress=_progress)
    total_ms = int((time.time() - t0) * 1000)
    summary = {
        "total":      len(outcomes),
        "ok":         sum(1 for o in outcomes if o.status == "ok"),
        "incomplete": sum(1 for o in outcomes if o.status == "incomplete"),
        "crash":      sum(1 for o in outcomes if o.status == "agent_crash"),
        "timeout":    sum(1 for o in outcomes if o.status == "agent_timeout"),
        "leakage":    sum(1 for o in outcomes if o.status == "leakage_detected"),
        "wall_ms":    total_ms,
    }
    print("\nsweep complete:", json.dumps(summary, indent=2))
    return 0 if summary["crash"] == 0 else 1


# ---------------------------- report / gc -----------------------------------

def _find_run_dir(run_id: str) -> Path | None:
    """Locate a run dir by run_id under exp/ (or legacy runs/)."""
    for root in (EXP_ROOT, RUNS_ROOT):
        if not root.is_dir():
            continue
        for meta in root.rglob("meta.json"):
            try:
                if json.loads(meta.read_text()).get("run_id") == run_id:
                    return meta.parent
            except Exception:                                          # noqa: BLE001
                continue
    return None


def cmd_report(args):
    # Allow either a run_id (searched under exp/) or a full run-dir path.
    arg = args.run_id
    p = Path(arg)
    run_dir = p if p.is_dir() and (p / "meta.json").exists() \
        else _find_run_dir(arg)
    if run_dir is None:
        print(f"unknown run_id or run-dir path: {arg}", file=sys.stderr)
        return 2
    meta = json.loads((run_dir / "meta.json").read_text())
    print(f"# run {meta.get('run_id', '?')}  ({run_dir})")
    print(json.dumps(meta, indent=2))
    sp = run_dir / "score_record.json"
    if sp.exists():
        print("\n## score record")
        print(sp.read_text())
    audit = run_dir / "network_audit.jsonl"
    if audit.exists():
        print("\n## network audit")
        print(audit.read_text())
    return 0


def _parse_age(s: str) -> timedelta:
    s = s.strip().lower()
    if s.endswith("h"):
        return timedelta(hours=float(s[:-1]))
    if s.endswith("m"):
        return timedelta(minutes=float(s[:-1]))
    if s.endswith("d"):
        return timedelta(days=float(s[:-1]))
    return timedelta(seconds=float(s))


def cmd_gc(args):
    """Walk exp/ and remove any run dir whose started_at is older than --older-than."""
    cutoff = datetime.now(timezone.utc) - _parse_age(args.older_than)
    roots = [r for r in (EXP_ROOT, RUNS_ROOT) if r.is_dir()]
    n_removed = 0
    for root in roots:
        for meta_p in root.rglob("meta.json"):
            try:
                started = datetime.fromisoformat(
                    json.loads(meta_p.read_text())["started_at"])
            except Exception:                                          # noqa: BLE001
                continue
            if started < cutoff:
                shutil.rmtree(meta_p.parent, ignore_errors=True)
                n_removed += 1
    print(f"gc: removed {n_removed} run dirs older than {args.older_than}")
    return 0


# ---------------------------- searxng -------------------------------------

def cmd_searxng(args):
    if args.action == "healthcheck":
        from .network import searxng_healthcheck
        rec = searxng_healthcheck()
        print(json.dumps(rec, indent=2))
        return 0 if rec.get("healthy") else 1
    if not SEARXNG_COMPOSE.exists():
        print(f"missing compose file: {SEARXNG_COMPOSE}", file=sys.stderr)
        return 2
    cmd = ["docker", "compose", "-f", str(SEARXNG_COMPOSE)]
    if args.action == "up":
        cmd += ["up", "-d"]
    elif args.action == "down":
        cmd += ["down"]
    else:
        print(f"unknown action: {args.action}", file=sys.stderr)
        return 2
    return subprocess.call(cmd)


# ---------------------------- argparse -------------------------------------

def _add_agent_flags(p):
    p.add_argument("--config", default=None, metavar="YAML",
                   help="experiment config file (see evsandbox/config.py); "
                        "flags given here override its values.")
    p.add_argument("--agent",
                   help="agent alias (default: smolagents_agent). "
                        "Resolves to 'python -m <alias>.worker' or via AGENT_ALIASES.")
    p.add_argument("--agent-cmd",
                   help="explicit agent command, overrides --agent. "
                        "e.g. 'python -m my_agent.worker'")
    p.add_argument("--agent-arg", action="append", default=[],
                   help="agent-specific arg key=value (repeatable). "
                        "Passed verbatim in AgentRequest.agent_args, on top "
                        "of the config file's agent.args.")
    p.add_argument("--target", default=None,
                   help="experiment identifier (e.g. 'test-turn1'). "
                        "Runs land in exp/<target>/<llm>/<tier>/<scenario>/<period>/. "
                        "Default: default-<YYYYMMDD>.")
    p.add_argument("--judge", default="mock",
                   choices=["mock", "anthropic", "claude_thinking",
                            "claude_cli", "openrouter", "self_hosted"],
                   help="LLM judge backend for scoring. "
                        "'mock' = deterministic stubs (default). "
                        "'anthropic' = Anthropic SDK (needs ANTHROPIC_API_KEY). "
                        "'claude_thinking' = Anthropic + extended thinking. "
                        "'claude_cli' = shells out to `claude -p` "
                        "(uses Claude Code OAuth if no ANTHROPIC_API_KEY). "
                        "'openrouter' = OpenAI-compat client at openrouter.ai "
                        "(needs OPENROUTER_API_KEY). "
                        "'self_hosted' = OpenAI-compat client at your own endpoint "
                        "(SELF_HOSTED_BASE_URL or --judge-base-url; key "
                        "SELF_HOSTED_API_KEY or 'EMPTY'; zero marginal cost; "
                        "needs --judge-model).")
    p.add_argument("--judge-model", default=None,
                   help="override default judge model. "
                        "claude_cli: 'sonnet' / 'opus' / full id. "
                        "openrouter: e.g. 'openai/gpt-5.4'. "
                        "self_hosted: the model your endpoint serves, e.g. "
                        "'DeepSeek-V4-Flash' (required). Default depends on backend.")
    p.add_argument("--judge-base-url", default=None,
                   help="self_hosted only: endpoint for the judge, overriding "
                        "SELF_HOSTED_BASE_URL (when the judge runs on another host).")
    p.add_argument("--judge-quality-model", default=None,
                   help="override judge model used ONLY for the report-quality "
                        "axis (the other 3 axes still use --judge-model). "
                        "Useful when you want a stronger judge for the more "
                        "subjective Quality rubric, e.g. "
                        "--judge self_hosted --judge-model DeepSeek-V4-Flash "
                        "--judge-quality-model DeepSeek-V4-Pro.")
    p.add_argument("--judge-thinking", default="middle",
                   choices=["low", "middle", "high"],
                   help="thinking tier for claude_thinking / claude_cli "
                        "(SDK: 2k/10k/20k tokens; CLI: --effort low/medium/high).")
    p.add_argument("--judge-max-tokens", type=int, default=None,
                   help="judge reply budget (default 2048).")
    p.add_argument("--judge-extra-body", type=json.loads, default=None, metavar="JSON",
                   help="extra request-body fields for self_hosted / openrouter judges, e.g. "
                        "'{\"chat_template_kwargs\": {\"thinking\": false}}' to turn "
                        "a reasoning model's thinking off.")
    p.add_argument("--judge-by-kind", type=json.loads, default=None, metavar="JSON",
                   help="per call kind (coverage, decompose, verify, quality), options "
                        "replacing --judge-max-tokens / --judge-extra-body, e.g. "
                        "'{\"verify\": {\"extra_body\": {\"reasoning_effort\": \"low\"}}}'.")


def _add_isolation_flag(p):
    p.add_argument("--isolation", default="none", choices=["none", "bwrap"],
                   help="'none' = plain subprocess with cwd = sandbox (default). "
                        "'bwrap' = run the agent under bubblewrap, seeing only "
                        "the sandbox and code, not the data trees "
                        "(see evsandbox/isolation.py).")


def main(argv=None):
    p = argparse.ArgumentParser(prog="evsandbox", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run")
    pr.add_argument("scenario_dir")
    pr.add_argument("period")
    pr.add_argument("--strategy", default="pass_through",
                    choices=["pass_through", "persona"])
    pr.add_argument("--seed", type=int, default=0)
    pr.add_argument("--timeout", type=int, default=300)
    pr.add_argument("--no-score", action="store_true")
    _add_isolation_flag(pr)
    _add_agent_flags(pr)
    pr.set_defaults(func=cmd_run)

    pe = sub.add_parser("e2e-sample")
    pe.add_argument("--strategy", default="pass_through",
                    choices=["pass_through", "persona"])
    pe.add_argument("--seed", type=int, default=0)
    pe.add_argument("--concurrency", type=int, default=1)
    pe.add_argument("--rpm-cap", type=int, default=600)
    pe.add_argument("--timeout", type=int, default=300)
    _add_agent_flags(pe)
    pe.set_defaults(func=cmd_e2e_sample)

    ps = sub.add_parser("sweep")
    ps.add_argument("--mode", default="independent",
                    choices=["independent", "episode"],
                    help="'independent' = each (scenario, period) is its own task "
                         "(no cross-period feedback); "
                         "'episode' = play each scenario's periods chronologically "
                         "with prior turn's score fed back to the agent.")
    ps.add_argument("--tier", default=None)
    ps.add_argument("--strategies", default="pass_through,persona")
    ps.add_argument("--seed", type=int, default=0)
    ps.add_argument("--concurrency", type=int, default=32)
    ps.add_argument("--rpm-cap", type=int, default=600)
    ps.add_argument("--max-tasks", type=int, default=0)
    ps.add_argument("--timeout", type=int, default=300,
                    help="seconds per task (independent) or per period (episode)")
    ps.add_argument("--feedback-mode", default="score",
                    choices=["none", "score", "detailed"],
                    help="(episode mode) how much information to feed back to "
                         "the agent after each turn.")
    _add_isolation_flag(ps)
    _add_agent_flags(ps)
    ps.set_defaults(func=cmd_sweep)

    pep = sub.add_parser("episode",
                         help="play all (or selected) periods of one scenario "
                              "in chronological order, with feedback between turns")
    pep.add_argument("scenario_dir")
    pep.add_argument("--periods", default=None,
                     help="comma-separated subset; default = all in chronological order")
    pep.add_argument("--strategy", default="pass_through",
                     choices=["pass_through", "persona"])
    pep.add_argument("--seed", type=int, default=0)
    pep.add_argument("--timeout", type=int, default=300,
                     help="seconds per period")
    pep.add_argument("--feedback-mode", default="score",
                     choices=["none", "score", "detailed"])
    _add_isolation_flag(pep)
    _add_agent_flags(pep)
    pep.set_defaults(func=cmd_episode)

    prep = sub.add_parser("report")
    prep.add_argument("run_id")
    prep.set_defaults(func=cmd_report)

    pgc = sub.add_parser("gc")
    pgc.add_argument("--older-than", default="24h")
    pgc.set_defaults(func=cmd_gc)

    psx = sub.add_parser("searxng")
    psx.add_argument("action", choices=["up", "down", "healthcheck"])
    psx.set_defaults(func=cmd_searxng)

    argv = list(argv) if argv is not None else sys.argv[1:]
    args = p.parse_args(argv)
    if getattr(args, "config", None):
        # Config values become this subcommand's defaults, so flags given on
        # the command line still win when argv is parsed again. Keys the
        # subcommand has no option for (e.g. `tier` for `run`) are skipped.
        cfg = load_config(args.config)
        cmd_parser = sub.choices[args.cmd]
        dests = {a.dest for a in cmd_parser._actions}
        cmd_parser.set_defaults(**{k: v for k, v in cfg.items() if k in dests})
        args = p.parse_args(argv)
        args.config_agent_args = cfg.get("agent_args") or {}
    if hasattr(args, "target"):
        args.target = args.target or _default_target()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
