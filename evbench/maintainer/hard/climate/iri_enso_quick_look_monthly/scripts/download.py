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
import shutil
import sys
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    TS_SOURCE, HEADERS, ONI_TXT_URL, ONI_CACHE_CANDIDATES, parse_oni_ascii,
)
import json
import time
from _common import (  # noqa: E402
    GT_SOURCE, HEADERS, ISSUE_URL_FMT, IRI_REQUEST_SLEEP_SEC,
    iter_months, period_to_mmm_yyyy, period_to_month_long,
)


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    out = TS_SOURCE / f"oni-{today}.ascii.txt"
    if out.exists() and not args.force:
        print(f"[skip] {out.name}")
        return 0

    # Try cached copies first.
    for cache_dir in ONI_CACHE_CANDIDATES:
        if not cache_dir.exists():
            continue
        snaps = sorted(cache_dir.glob("oni-*.ascii.txt"))
        if not snaps:
            continue
        shutil.copy(snaps[-1], out)
        rows = parse_oni_ascii(out.read_text(encoding="utf-8"))
        print(f"[cache] copied {snaps[-1].name} -> {out.name} "
              f"({len(rows)} rows; latest {rows[-1]['season']} {rows[-1]['year']})")
        return 0

    r = requests.get(ONI_TXT_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    out.write_text(r.text, encoding="utf-8")
    rows = parse_oni_ascii(r.text)
    print(f"[fetch] {out.name} ({len(rows)} rows; latest "
          f"{rows[-1]['season']} {rows[-1]['year']})")
    return 0


# --- step: gt ------------------------------------------------------------
LANDING_PATH = Path(__file__).parent / "landing_urls.json"


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    known_missing = set(
        json.loads(LANDING_PATH.read_text()).get("missing_months_known", [])
    )

    n_ok = n_skip = n_miss = 0
    for period in iter_months(args.instance_start, args.instance_end):
        out = GT_SOURCE / f"{period}.html"
        if out.exists() and not args.force:
            print(f"[skip] {period}")
            n_skip += 1
            continue
        if period in known_missing:
            print(f"[gap]  {period}: known-missing")
            n_miss += 1
            continue
        month_long, year = period_to_month_long(period)
        url = ISSUE_URL_FMT.format(month_long=month_long, year=year)
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
        except requests.RequestException as e:
            print(f"[err]  {period}: {e}")
            n_miss += 1
            time.sleep(IRI_REQUEST_SLEEP_SEC); continue
        if r.status_code != 200:
            print(f"[err]  {period}: HTTP {r.status_code}")
            n_miss += 1
            time.sleep(IRI_REQUEST_SLEEP_SEC); continue
        out.write_text(r.text, encoding="utf-8")
        n_ok += 1
        print(f"[ok]   {period}: {len(r.text):,} bytes")
        time.sleep(IRI_REQUEST_SLEEP_SEC)
    print(f"\n[done] ok={n_ok}  skip={n_skip}  miss={n_miss}")
    return 0 if n_miss == 0 else 1

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
