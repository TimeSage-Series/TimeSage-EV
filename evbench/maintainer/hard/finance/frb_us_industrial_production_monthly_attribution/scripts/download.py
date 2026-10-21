#!/usr/bin/env python3
"""Download this scenario's source artifacts.

    python scripts/download.py                 # every step, in order: timeseries -> gt
    python scripts/download.py timeseries    # one step
    python scripts/download.py gt [flags]    # …with that step's own flags
    python scripts/download.py all [flags]     # every step, flags forwarded to each
    python scripts/download.py --list          # list the steps

Merged from download_timeseries.py and download_gt.py. Each step keeps the argument
parser it had before, so every flag that used to work still works — pass it
after the step name.
"""
from __future__ import annotations
import subprocess
import sys
import urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import FRED_CSV_URL, SERIES_ID, TS_SOURCE
import shutil
from _common import GT_SOURCE, SERIES_ID, TS_SOURCE


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> int:
    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    params = {"id": SERIES_ID, "cosd": "2017-01-01", "coed": "2026-04-30"}
    url = f"{FRED_CSV_URL}?{urllib.parse.urlencode(params)}"
    dest = TS_SOURCE / f"{SERIES_ID}.csv"
    print(f"downloading {SERIES_ID} -> {dest}", file=sys.stderr)
    res = subprocess.run(
        ["curl", "-sLf", "--max-time", "60", "-o", str(dest), url],
        check=False,
    )
    if res.returncode != 0:
        print(f"curl failed for {SERIES_ID}: exit {res.returncode}",
              file=sys.stderr)
        return 1
    return 0


# --- step: gt ------------------------------------------------------------
def _step_gt() -> int:
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    src = TS_SOURCE / f"{SERIES_ID}.csv"
    dst = GT_SOURCE / f"{SERIES_ID}.csv"
    if not src.exists():
        print(f"MISSING: {src}", file=sys.stderr)
        return 1
    shutil.copy2(src, dst)
    print(f"copied {src.name} -> {dst}", file=sys.stderr)
    return 0

# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------

#: Execution order. The ground truth is derived from the series, so timeseries runs first.
STEPS = ("timeseries", "gt")

_STEP_FUNCS = {
    "timeseries": _step_timeseries,
    "gt": _step_gt,
}


def _run_step(step: str, args: list) -> int:
    """Invoke one step with `args` as its argv, then restore the real argv."""
    saved = sys.argv
    sys.argv = [f"{Path(__file__).name} {step}"] + list(args)
    try:
        return int(_STEP_FUNCS[step]() or 0)
    finally:
        sys.argv = saved


def main() -> int:
    argv = sys.argv[1:]

    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv and argv[0] == "--list":
        for step in STEPS:
            print(step)
        return 0

    if argv and argv[0] in STEPS:
        return _run_step(argv[0], argv[1:])

    # No step named: run all of them. Bare invocation passes no flags; an
    # explicit `all` forwards whatever follows to every step.
    rest = argv[1:] if (argv and argv[0] == "all") else []
    if argv and argv[0] != "all":
        print(f"unknown step {argv[0]!r}; expected one of {', '.join(STEPS)}, "
              f"or 'all'", file=sys.stderr)
        return 2

    for step in STEPS:
        rc = _run_step(step, rest)
        if rc:
            print(f"[{Path(__file__).name}] step {step!r} exited {rc}; stopping",
                  file=sys.stderr)
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
