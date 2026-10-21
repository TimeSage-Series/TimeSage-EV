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
from _common import (  # noqa: E402
    TS_SOURCE, GT_SOURCE, NCEI_URL_PATTERN, HEADERS,
    REQUEST_SLEEP_SEC, iter_periods, period_to_yyyymm,
)


# --- step: timeseries ----------------------------------------------------


LANDING_PATH = Path(__file__).parent / "landing_urls.json"


def fetch(period: str) -> bytes | None:
    yyyymm = period_to_yyyymm(period)
    url = NCEI_URL_PATTERN.format(period=yyyymm)
    try:
        r = requests.get(url, headers=HEADERS, timeout=60, allow_redirects=True)
    except requests.RequestException as e:
        print(f"[err]  {period}: {e}", flush=True)
        return None
    if r.status_code == 404:
        print(f"[404]  {period}: not published at {url}", flush=True)
        return None
    if r.status_code != 200:
        print(f"[err]  {period}: HTTP {r.status_code} from {url}", flush=True)
        return None
    return r.content


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, help="YYYY-MM inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-MM inclusive")
    ap.add_argument("--force", action="store_true",
                    help="Re-fetch even if the HTML is already cached.")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    GT_SOURCE.mkdir(parents=True, exist_ok=True)

    landing = json.loads(LANDING_PATH.read_text())
    known_missing = set(landing.get("known_missing_or_late_periods", []))
    overrides = landing.get("manual_overrides", {})

    n_ok = 0
    n_skip = 0
    n_miss = 0
    for period in iter_periods(args.start, args.end):
        out_ts = TS_SOURCE / f"global-climate-{period_to_yyyymm(period)}.html"
        out_gt = GT_SOURCE / f"global-climate-{period_to_yyyymm(period)}.html"
        if out_ts.exists() and out_gt.exists() and not args.force:
            print(f"[skip] {period}: cached", flush=True)
            n_skip += 1
            continue
        if period in known_missing:
            print(f"[gap]  {period}: marked known-missing in landing_urls.json",
                  flush=True)
            n_miss += 1
            continue
        if period in overrides:
            url = overrides[period]
            try:
                r = requests.get(url, headers=HEADERS, timeout=60,
                                 allow_redirects=True)
                r.raise_for_status()
                content = r.content
                print(f"[ovr]  {period}: fetched override {url}", flush=True)
            except requests.RequestException as e:
                print(f"[err]  {period}: override {url} -> {e}", flush=True)
                content = None
        else:
            content = fetch(period)

        if content is None:
            n_miss += 1
            time.sleep(REQUEST_SLEEP_SEC)
            continue

        out_ts.write_bytes(content)
        out_gt.write_bytes(content)
        n_ok += 1
        print(f"[ok]   {period}: {len(content):,} bytes", flush=True)
        time.sleep(REQUEST_SLEEP_SEC)

    print(f"\n[done] ok={n_ok}  skip={n_skip}  miss={n_miss}", flush=True)
    return 0 if n_miss == 0 else 1


# --- step: gt ------------------------------------------------------------
def _step_gt() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, help="YYYY-MM inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-MM inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    landing = json.loads(LANDING_PATH.read_text())
    known_missing = set(landing.get("known_missing_or_late_periods", []))
    overrides = landing.get("manual_overrides", {})

    n_present = 0
    n_fetched = 0
    n_missing = 0
    for period in iter_periods(args.start, args.end):
        yyyymm = period_to_yyyymm(period)
        out_gt = GT_SOURCE / f"global-climate-{yyyymm}.html"
        if out_gt.exists() and not args.force:
            print(f"[ok]   {period}: already in gt_source/", flush=True)
            n_present += 1
            continue
        if period in known_missing:
            print(f"[gap]  {period}: known-missing", flush=True)
            n_missing += 1
            continue

        # Mirror from timeseries_source if it exists; otherwise fetch.
        src_ts = TS_SOURCE / f"global-climate-{yyyymm}.html"
        if src_ts.exists() and not args.force:
            out_gt.write_bytes(src_ts.read_bytes())
            print(f"[mir]  {period}: mirrored from timeseries_source/", flush=True)
            n_present += 1
            continue

        url = overrides.get(period) or NCEI_URL_PATTERN.format(period=yyyymm)
        try:
            r = requests.get(url, headers=HEADERS, timeout=60,
                             allow_redirects=True)
        except requests.RequestException as e:
            print(f"[err]  {period}: {e}", flush=True)
            n_missing += 1
            time.sleep(REQUEST_SLEEP_SEC)
            continue
        if r.status_code != 200:
            print(f"[err]  {period}: HTTP {r.status_code}", flush=True)
            n_missing += 1
            time.sleep(REQUEST_SLEEP_SEC)
            continue

        out_gt.write_bytes(r.content)
        # Also mirror into timeseries_source if absent.
        if not src_ts.exists():
            src_ts.write_bytes(r.content)
        n_fetched += 1
        print(f"[ok]   {period}: fetched {len(r.content):,} bytes",
              flush=True)
        time.sleep(REQUEST_SLEEP_SEC)

    print(f"\n[done] present={n_present}  fetched={n_fetched}  missing={n_missing}",
          flush=True)
    return 0 if n_missing == 0 else 1

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
