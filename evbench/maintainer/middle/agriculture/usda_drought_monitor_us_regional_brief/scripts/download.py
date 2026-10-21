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
import urllib.parse
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, HEADERS, iter_weeks  # noqa: E402
from _common import GT_SOURCE, HEADERS, iter_weeks, iso_label  # noqa: E402


# --- step: timeseries ----------------------------------------------------

BASE = "https://usdmdataservices.unl.edu/api"


def fetch_conus_window(start_date, end_date) -> str:
    params = {
        "aoi": "conus",
        "startdate": f"{start_date.month}/{start_date.day}/{start_date.year}",
        "enddate":   f"{end_date.month}/{end_date.day}/{end_date.year}",
        "statisticsType": 1,
    }
    url = f"{BASE}/USStatistics/GetDroughtSeverityStatisticsByAreaPercent?{urllib.parse.urlencode(params)}"
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.text


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-Www inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-Www inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    weeks = list(iter_weeks(args.start, args.end))
    if not weeks:
        print("[err] no weeks", flush=True); return
    first_tue = weeks[0][2]; last_tue = weeks[-1][2]
    conus_path = TS_SOURCE / f"conus_{args.start}_{args.end}.csv"
    if conus_path.exists() and not args.force:
        print(f"[skip] {conus_path.name}", flush=True); return
    try:
        csv_text = fetch_conus_window(first_tue, last_tue)
        conus_path.write_text(csv_text)
        n = max(0, csv_text.count("\n") - 1)
        print(f"[ok]  CONUS window {first_tue}..{last_tue}: {n} rows", flush=True)
    except requests.HTTPError as e:
        print(f"[err] {e}", flush=True)
    time.sleep(0.3)


# --- step: gt ------------------------------------------------------------
SUMMARY_URL = "https://droughtmonitor.unl.edu/Summary.aspx?{ymd}"
# Verified pattern: /data/pdf/<YYYYMMDD>/<YYYYMMDD>_usdm.pdf — date prefix repeats.
PDF_URL     = "https://droughtmonitor.unl.edu/data/pdf/{ymd}/{ymd}_usdm.pdf"


def _get(url: str, dest: Path, min_bytes: int = 500) -> str:
    r = requests.get(url, headers=HEADERS, timeout=60)
    if r.status_code != 200:
        return f"HTTP {r.status_code}"
    if len(r.content) < min_bytes:
        return f"too small ({len(r.content)} bytes)"
    dest.write_bytes(r.content)
    return "ok"


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-Www inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-Www inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)

    for y, w, tue in iter_weeks(args.start, args.end):
        label = iso_label(y, w)
        ymd = f"{tue.year:04d}{tue.month:02d}{tue.day:02d}"
        html_path = GT_SOURCE / f"{label}.html"
        pdf_path  = GT_SOURCE / f"{label}.pdf"

        if html_path.exists() and not args.force:
            print(f"[skip] {label}.html", flush=True)
        else:
            status = _get(SUMMARY_URL.format(ymd=ymd), html_path, min_bytes=1_000)
            print(f"[{status:6s}] {label}.html", flush=True)
            time.sleep(0.5)

        if pdf_path.exists() and not args.force:
            print(f"[skip] {label}.pdf", flush=True)
        else:
            status = _get(PDF_URL.format(ymd=ymd), pdf_path, min_bytes=10_000)
            print(f"[{status:6s}] {label}.pdf", flush=True)
            time.sleep(0.5)

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
