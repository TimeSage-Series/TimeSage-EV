"""Run the agent inside a bubblewrap (bwrap) sandbox instead of a bare subprocess.

A plain subprocess only gets cwd=<world root>; it can still read the whole
host, including every instance's ground_truth.json. Under bwrap the agent
sees a filesystem assembled from explicit mounts and nothing else:

    /root        the period's sandbox (read-write)  — timeseries.csv, gt_source/, …
    /out         this run's output dir (read-write) — trace.jsonl, network audit
    /usr, /etc   the host system (read-only)
    <prefix>     the Python interpreter + site-packages (read-only)
    <code>       evsandbox, agents, and evbench's engine/evaluator/tasks (read-only)
    <config>     the DNS resolver config and $TIMESAGE_MODELS_CONFIG (read-only)

The data trees (evbench/scenarios/, scenarios_hf/), the maintainer, exp/ and
the evaluator's fixtures are not mounted. The network is shared: agents call
LLM APIs, and web access is audited separately (network.py).

bwrap needs no root and no daemon, only unprivileged user namespaces.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SANDBOX_ROOT = "/root"
OUT_DIR = "/out"

#: Repo paths an agent may import from. Everything else in the repo stays hidden.
CODE_MOUNTS = (
    REPO / "evsandbox",
    REPO / "agents",
    REPO / "evbench" / "__init__.py",
    REPO / "evbench" / "engine",
    REPO / "evbench" / "evaluator",
    REPO / "evbench" / "tasks",
)
#: Env vars naming a host file the agent needs to read; the file is mounted
#: read-only at the same path.
FILE_ENV_VARS = ("TIMESAGE_MODELS_CONFIG",)

#: Inside the code mounts, but holding answers: an agent output with its
#: ground truth, and aggregated score reports.
MASKED = (
    REPO / "evbench" / "evaluator" / "fixtures",
    REPO / "evbench" / "evaluator" / "reports",
)


def bwrap_available() -> bool:
    return shutil.which("bwrap") is not None


def _under(path: Path, roots: list[Path]) -> bool:
    return any(path == r or r in path.parents for r in roots)


def bwrap_command(cmd: list[str], env: dict[str, str], *,
                  world_root: Path, run_dir: Path) -> tuple[list[str], dict[str, str]]:
    """Wrap `cmd` so it runs in a bwrap sandbox; returns (argv, env).

    Host paths in `env` that point into `run_dir` or `world_root` are rewritten
    to their in-sandbox locations.
    """
    if not bwrap_available():
        raise RuntimeError("isolation='bwrap' requested but bwrap is not on PATH")

    ro: list[Path] = []
    for p in (Path(sys.prefix), Path(sys.base_prefix), *CODE_MOUNTS):
        if p.exists() and not _under(p, ro):
            ro.append(p)
    # A script named on the command line (`python /path/agent.py`) must be
    # visible too; only the file itself is mounted, not its directory.
    for tok in cmd:
        p = Path(tok)
        if p.is_absolute() and p.is_file() and not _under(p.resolve(), ro):
            ro.append(p.resolve())
    for var in FILE_ENV_VARS:
        p = Path(env[var]) if env.get(var) else None
        if p is not None and p.is_file() and not _under(p, ro):
            ro.append(p)
    # /etc/resolv.conf is often a symlink into /run (systemd-resolved);
    # without its target the agent cannot resolve any API host.
    resolv = Path("/etc/resolv.conf").resolve()
    if resolv.exists() and not _under(resolv, [Path("/etc"), Path("/usr")]):
        ro.append(resolv.parent)

    argv = ["bwrap",
            "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/bin", "/bin",
            "--symlink", "usr/sbin", "/sbin",
            "--symlink", "usr/lib", "/lib",
            "--symlink", "usr/lib64", "/lib64",
            "--ro-bind", "/etc", "/etc",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for p in ro:
        argv += ["--ro-bind", str(p), str(p)]
    for p in MASKED:
        if p.exists() and _under(p, ro):
            argv += ["--tmpfs", str(p)]
    argv += ["--bind", str(world_root), SANDBOX_ROOT,
             "--bind", str(run_dir), OUT_DIR,
             "--chdir", SANDBOX_ROOT,
             "--unshare-all", "--share-net",
             "--die-with-parent", "--new-session",
             "--"] + cmd

    inner = {k: v.replace(str(run_dir), OUT_DIR).replace(str(world_root), SANDBOX_ROOT)
             for k, v in env.items()}
    inner["HOME"] = "/tmp"
    return argv, inner
