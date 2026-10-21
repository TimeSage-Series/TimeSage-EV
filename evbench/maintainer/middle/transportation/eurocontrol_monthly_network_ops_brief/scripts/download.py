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
import shutil
import sys
from pathlib import Path
from _common import TS_SOURCE, REPORT_MONTHS, url_for, ym_label, http_get
from _common import TS_SOURCE, GT_SOURCE, REPORT_MONTHS, ym_label


# --- step: timeseries ----------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[6]
V0_REPORTS_DIR = (
    REPO_ROOT
    / "../TimeSage-EV/scenarios_v0/transportation/transport-eurocontrol-monthly/reports"
).resolve()


def _step_timeseries() -> int:
    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    for y, m in REPORT_MONTHS:
        lbl = ym_label(y, m)
        dest = TS_SOURCE / f"{lbl}.html"
        if dest.exists():
            print(f"already have {dest.name}", file=sys.stderr)
            continue
        v0 = V0_REPORTS_DIR / f"eurocontrol_{lbl}.html"
        if v0.exists():
            shutil.copy2(v0, dest)
            print(f"copied v0 {v0.name} -> {dest.name}", file=sys.stderr)
            continue
        url = url_for(y, m)
        print(f"downloading {url}", file=sys.stderr)
        http_get(url, dest)
    return 0


# --- step: gt ------------------------------------------------------------
def _step_gt() -> int:
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    for y, m in REPORT_MONTHS:
        lbl = ym_label(y, m)
        src = TS_SOURCE / f"{lbl}.html"
        if not src.exists():
            print(f"MISSING: {src}", file=sys.stderr)
            continue
        shutil.copy2(src, GT_SOURCE / f"{lbl}.html")
    print(f"mirrored to {GT_SOURCE}", file=sys.stderr)
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
