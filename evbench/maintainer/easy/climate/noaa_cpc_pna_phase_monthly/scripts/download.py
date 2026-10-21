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
import argparse
import datetime as dt
import sys
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, PNA_TXT_URL, HEADERS  # noqa: E402
from _common import GT_SOURCE, PNA_DASHBOARD_URL, HEADERS  # noqa: E402


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    out = TS_SOURCE / f"pna-{today}.ascii.txt"
    if out.exists() and not args.force:
        print(f"[skip] {out.name} already exists; pass --force to re-download.")
        return 0
    r = requests.get(PNA_TXT_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    out.write_text(r.text, encoding="utf-8")
    n = sum(1 for x in r.text.splitlines() if x.strip())
    print(f"[ok] wrote {out} ({len(r.text):,} bytes; {n} non-empty lines)")
    return 0


# --- step: gt ------------------------------------------------------------
def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    out = GT_SOURCE / f"pna-dashboard-{today}.html"
    if out.exists() and not args.force:
        print(f"[skip] {out.name} already exists; pass --force to re-download.")
        return 0
    r = requests.get(PNA_DASHBOARD_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    out.write_text(r.text, encoding="utf-8")
    print(f"[ok] wrote {out} ({len(r.text):,} bytes)")
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
