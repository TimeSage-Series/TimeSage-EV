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
import json
import sys
import time
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, HEADERS, html_filename  # noqa: E402
import shutil
from _common import TS_SOURCE, GT_SOURCE  # noqa: E402


# --- step: timeseries ----------------------------------------------------

URLS_JSON = Path(__file__).parent / "_discovered_urls.json"


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=24,
                    help="Number of most-recent weeks to download.")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    records = json.loads(URLS_JSON.read_text())[: args.count]
    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    fetched, skipped, failed = 0, 0, []
    import datetime as dt

    for rec in records:
        d = dt.date.fromisoformat(rec["date"])
        dest = TS_SOURCE / html_filename(d)
        if dest.exists() and not args.force:
            print(f"[skip] {rec['date']} (cached)", flush=True)
            skipped += 1
            continue
        try:
            r = requests.get(rec["url"], headers=HEADERS, timeout=60)
            if r.status_code == 200 and len(r.text) > 2_000:
                dest.write_text(r.text, encoding="utf-8")
                fetched += 1
                print(f"[ok]   {rec['date']}  {len(r.text)} bytes", flush=True)
            else:
                failed.append((rec["date"], f"HTTP {r.status_code}"))
                print(f"[fail] {rec['date']}: HTTP {r.status_code}", flush=True)
        except requests.RequestException as e:
            failed.append((rec["date"], str(e)))
            print(f"[err]  {rec['date']}: {e}", flush=True)
        time.sleep(1.5)

    print(f"\nSummary: fetched={fetched} skipped={skipped} failed={len(failed)}",
          flush=True)
    for d, why in failed:
        print(f"  - {d}: {why}", flush=True)


# --- step: gt ------------------------------------------------------------
def _step_gt() -> None:
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(TS_SOURCE.glob("freightos_*.html")):
        dst = GT_SOURCE / f.name
        if not dst.exists():
            shutil.copy2(f, dst)
            n += 1
    print(f"[done] mirrored {n} files to {GT_SOURCE}", flush=True)

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
