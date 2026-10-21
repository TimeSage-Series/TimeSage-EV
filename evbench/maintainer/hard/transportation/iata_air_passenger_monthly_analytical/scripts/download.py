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
from _common import (  # noqa: E402
    TS_SOURCE, HEADERS, iter_months, iata_url, pdf_filename, month_label,
)
import shutil
from _common import (  # noqa: E402
    TS_SOURCE, GT_SOURCE, HEADERS, iter_months, iata_url, pdf_filename, month_label,
)


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-MM inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    for d in iter_months(args.start, args.end):
        label = month_label(d)
        dest = TS_SOURCE / pdf_filename(d)
        if dest.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue
        url = iata_url(d)
        try:
            r = requests.get(url, headers=HEADERS, timeout=120, allow_redirects=True)
            ct = r.headers.get("content-type", "")
            looks_pdf = (
                r.status_code == 200
                and len(r.content) > 50_000
                and (b"%PDF" in r.content[:1024] or "pdf" in ct.lower())
            )
            if looks_pdf:
                dest.write_bytes(r.content)
                print(f"[ok]    {label} ({len(r.content)} B)", flush=True)
            else:
                print(f"[fail]  {label}: HTTP {r.status_code} "
                      f"({len(r.content)} B, {ct})", flush=True)
                missing.append(label)
        except requests.RequestException as e:
            print(f"[err]   {label}: {e}", flush=True)
            missing.append(label)
        time.sleep(1.5)

    if missing:
        print(f"\n[summary] Missing months ({len(missing)}): {missing}", flush=True)
        if len(missing) > 2:
            print("[warn] >2 months missing — consider quarantining per scenario brief.",
                  flush=True)


# --- step: gt ------------------------------------------------------------
def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-MM inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    for d in iter_months(args.start, args.end):
        label = month_label(d)
        dest = GT_SOURCE / pdf_filename(d)
        src = TS_SOURCE / pdf_filename(d)
        if dest.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue
        # Prefer copying from timeseries_source/ to guarantee byte-identity.
        if src.exists():
            shutil.copy(src, dest)
            print(f"[copy] {label} (from timeseries_source)", flush=True)
            continue
        # Fallback: fetch directly.
        url = iata_url(d)
        try:
            r = requests.get(url, headers=HEADERS, timeout=120, allow_redirects=True)
            ct = r.headers.get("content-type", "")
            looks_pdf = (
                r.status_code == 200
                and len(r.content) > 50_000
                and (b"%PDF" in r.content[:1024] or "pdf" in ct.lower())
            )
            if looks_pdf:
                dest.write_bytes(r.content)
                print(f"[ok]    {label} ({len(r.content)} B)", flush=True)
            else:
                print(f"[fail]  {label}: HTTP {r.status_code} "
                      f"({len(r.content)} B, {ct})", flush=True)
        except requests.RequestException as e:
            print(f"[err]   {label}: {e}", flush=True)
        time.sleep(1.5)

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
