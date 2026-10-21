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
import sys
import time
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, HEADERS, iter_months, month_label, cass_url  # noqa: E402
import shutil
from _common import TS_SOURCE, GT_SOURCE, iter_months, month_label  # noqa: E402


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-MM inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    skipped: list[tuple[str, str]] = []
    fetched = 0

    for d in iter_months(args.start, args.end):
        label = month_label(d)
        url = cass_url(d)
        dest = TS_SOURCE / f"cass_{label}.html"
        if dest.exists() and not args.force:
            print(f"[skip] {label} (cached)", flush=True)
            continue
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 200 and len(r.text) > 2_000:
                dest.write_text(r.text, encoding="utf-8")
                fetched += 1
                print(f"[ok]   {label}  {len(r.text)} bytes", flush=True)
            else:
                msg = f"HTTP {r.status_code} ({len(r.text)} bytes)"
                skipped.append((label, msg))
                print(f"[fail] {label}: {msg}", flush=True)
        except requests.RequestException as e:
            skipped.append((label, str(e)))
            print(f"[err]  {label}: {e}", flush=True)
        time.sleep(2.0)

    print(f"\nSummary: fetched={fetched}  skipped={len(skipped)}", flush=True)
    for lab, why in skipped:
        print(f"  - {lab}: {why}", flush=True)


# --- step: gt ------------------------------------------------------------
def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-MM inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    copied = 0
    missing: list[str] = []

    for d in iter_months(args.start, args.end):
        label = month_label(d)
        src = TS_SOURCE / f"cass_{label}.html"
        dst = GT_SOURCE / f"cass_{label}.html"
        if not src.exists():
            missing.append(label)
            print(f"[miss] {label}: source HTML not found", flush=True)
            continue
        if dst.exists() and not args.force and dst.stat().st_mtime >= src.stat().st_mtime:
            print(f"[skip] {label}", flush=True)
            continue
        shutil.copy2(src, dst)
        copied += 1
        print(f"[ok]   {label}", flush=True)

    print(f"\nSummary: copied={copied}  missing_source={len(missing)}", flush=True)

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
