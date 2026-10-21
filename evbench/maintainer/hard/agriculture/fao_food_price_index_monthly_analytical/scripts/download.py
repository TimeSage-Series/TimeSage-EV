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
from pathlib import Path
import argparse
import sys
import urllib.request
sys.path.insert(0, str(Path(__file__).parent))
from _common import HEADERS, TS_SOURCE  # noqa: E402


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> None:
    root = Path(__file__).resolve().parents[1]
    print(f"Source artifacts are checked in under {root / 'timeseries_source'}")


# --- step: gt ------------------------------------------------------------
CSV_URL = (
    "https://www.fao.org/media/docs/worldfoodsituationlibraries/"
    "default-document-library/food_price_indices_data.csv"
)
CSV_DEST = TS_SOURCE / "food_price_indices_data.csv"


def download(url: str, dest: Path, refresh: bool = False) -> None:
    if dest.exists() and dest.stat().st_size > 5000 and not refresh:
        print(f"[skip] {dest.name} already present ({dest.stat().st_size} bytes)")
        return
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"[ok]   {dest.name} <- {url} ({len(data)} bytes)")


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="Re-download even if file exists.")
    args = ap.parse_args()
    download(CSV_URL, CSV_DEST, refresh=args.refresh)
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
