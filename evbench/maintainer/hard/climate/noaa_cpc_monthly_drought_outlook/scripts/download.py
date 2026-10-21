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
import time
import urllib.parse
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from _common import (   # noqa: E402
    TS_SOURCE, HEADERS, USDM_API_BASE, iter_months, month_label,
    last_day_of_month, release_date_for,
)
import json
from _common import (   # noqa: E402
    GT_SOURCE, HEADERS, CPC_SLEEP_SECONDS, iter_months, month_label,
    archive_url,
)


# --- step: timeseries ----------------------------------------------------


# We want USDM history back >= 2 years before the earliest instance.
# Instance window starts at forecast 2024-06 (released 2024-05-31). Two
# full years before the release date is 2022-05-31. We back-stop the
# fetch at the Tuesday on-or-before 2022-05-31 (=2022-05-31 is itself a
# Tuesday).
DEFAULT_FETCH_BACKSTOP = "2022-05-31"


def fetch_conus_window(start: dt.date, end: dt.date) -> str:
    params = {
        "aoi": "conus",
        "startdate": f"{start.month}/{start.day}/{start.year}",
        "enddate":   f"{end.month}/{end.day}/{end.year}",
        "statisticsType": 1,
    }
    url = (
        f"{USDM_API_BASE}/USStatistics/"
        f"GetDroughtSeverityStatisticsByAreaPercent?"
        f"{urllib.parse.urlencode(params)}"
    )
    r = requests.get(url, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.text


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True,
                    help="forecast YYYY-MM of earliest instance")
    ap.add_argument("--instance-end", required=True,
                    help="forecast YYYY-MM of latest instance")
    ap.add_argument("--backstop", default=DEFAULT_FETCH_BACKSTOP,
                    help="earliest week_ending to fetch (YYYY-MM-DD)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)

    start = dt.date.fromisoformat(args.backstop)
    # End is the release date of the LATEST instance (so we never fetch
    # weeks that would leak into a not-yet-released MDO).
    y, m = args.instance_end.split("-"); y, m = int(y), int(m)
    end = release_date_for(y, m)

    fname = f"conus_{start.isoformat()}_{end.isoformat()}.csv"
    out = TS_SOURCE / fname
    if out.exists() and not args.force:
        print(f"[skip] {fname} already exists", flush=True)
        return

    print(f"[fetch] USDM CONUS {start} .. {end}", flush=True)
    csv_text = fetch_conus_window(start, end)
    out.write_text(csv_text, encoding="utf-8")
    n = max(0, csv_text.count("\n") - 1)
    print(f"[ok]    wrote {fname} ({n} rows)", flush=True)
    time.sleep(0.3)


# --- step: gt ------------------------------------------------------------
LANDING_PATH = Path(__file__).parent / "landing_urls.json"


def fetch_text(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    # CPC serves the narrative as text/plain.
    return r.text


def wrap_html(text: str, url: str, label: str) -> str:
    return (
        "<!doctype html>\n"
        f"<html><head><meta charset='utf-8'><title>NOAA CPC Monthly Drought "
        f"Outlook — {label}</title></head><body>\n"
        f"<!-- source: {url} -->\n"
        f"<pre>\n{text}\n</pre>\n"
        "</body></html>\n"
    )


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="forecast YYYY-MM inclusive")
    ap.add_argument("--end",   required=True, help="forecast YYYY-MM inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    landing_data = json.loads(LANDING_PATH.read_text())
    known_missing = set(landing_data.get("missing_months_known", []))
    urls = landing_data.get("archive_urls", {})

    for y, m in iter_months(args.start, args.end):
        label = month_label(y, m)
        out = GT_SOURCE / f"{label}.html"
        if out.exists() and not args.force:
            print(f"[skip] {label}", flush=True)
            continue
        if label in known_missing:
            print(f"[gap]  {label}: known missing", flush=True)
            continue
        url = urls.get(label) or archive_url(y, m)
        try:
            text = fetch_text(url)
            out.write_text(wrap_html(text, url, label), encoding="utf-8")
            print(f"[ok]   {label}: {len(text):,} bytes -> {url.split('/')[-1]}",
                  flush=True)
        except requests.HTTPError as e:
            print(f"[err]  {label}: {e} ({url})", flush=True)
        time.sleep(CPC_SLEEP_SECONDS)

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
