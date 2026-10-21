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
import urllib.parse
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from _common import (TS_SOURCE, SOCRATA_URL, TARGET_SITE, PATHOGEN_TARGET,
                     week_label, iter_weeks)  # noqa
import shutil
from _common import TS_SOURCE, GT_SOURCE, week_label, iter_weeks  # noqa

def _safe_copy(src, dst, _c=shutil.copy2):
    """Copy unless src and dst are the same file.

    gt_source/ and timeseries_source/ used to be separate directories, so a
    scenario could legitimately copy an artifact from one into the other. They
    are now one source/ tree, which turns those copies into copy-onto-self and
    raises SameFileError — bts_airline_load_factor_monthly failed exactly this
    way on loadfactor.csv.
    """
    from pathlib import Path as _P
    s, d = _P(src), _P(dst)
    try:
        if s.resolve() == d.resolve():
            return d
    except OSError:
        pass
    d.parent.mkdir(parents=True, exist_ok=True)
    return _c(str(s), str(d))



# --- step: timeseries ----------------------------------------------------


def fetch_week(saturday) -> list:
    # atcp-73re stores week_end as a plain text column ("YYYY-MM-DD"), not
    # as a calendar_date — so we must NOT append a "T00:00:00.000" suffix.
    where = (f"site='{TARGET_SITE}' "
             f"AND pathogen_target='{PATHOGEN_TARGET}' "
             f"AND week_end='{saturday.isoformat()}'")
    params = {"$limit": 200, "$where": where}
    url = f"{SOCRATA_URL}?{urllib.parse.urlencode(params)}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-Www inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-Www inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)

    for y, w, sat in iter_weeks(args.start, args.end):
        label = week_label(sat)
        path = TS_SOURCE / f"{label}.json"
        # A week fetched before CDC published it is saved with no rows; that
        # placeholder must not count as downloaded or the week never fills in.
        if (path.exists() and not args.force
                and json.loads(path.read_text()).get("rows")):
            print(f"[skip] {label}", flush=True); continue
        try:
            rows = fetch_week(sat)
            payload = {"iso_week": label, "saturday": sat.isoformat(),
                       "pathogen_target": PATHOGEN_TARGET, "site": TARGET_SITE,
                       "rows": rows}
            path.write_text(json.dumps(payload, indent=2))
            if rows:
                wval = rows[0].get("site_wval", "(unknown)")
                print(f"[ok]   {label}: 1 row, site_wval={wval}", flush=True)
            else:
                print(f"[empty]{label}: no row published yet", flush=True)
        except requests.HTTPError as e:
            print(f"[err]  {label}: {e}", flush=True)
        time.sleep(0.3)


# --- step: gt ------------------------------------------------------------
def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)

    for y, w, sat in iter_weeks(args.start, args.end):
        label = week_label(sat)
        src = TS_SOURCE / f"{label}.json"
        dst = GT_SOURCE / f"{label}.json"
        if not src.exists():
            print(f"[skip] {label}: timeseries_source missing — run `download.py timeseries` first", flush=True)
            continue
        if dst.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue
        _safe_copy(src, dst)
        print(f"[ok]   {label}", flush=True)

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
