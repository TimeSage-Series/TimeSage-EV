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
import csv
import datetime as dt
import io
import json
import sys
import urllib.parse
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from _common import (TS_SOURCE, FRED_CSV_URL, SERIES_ID, classify,
                     week_label, monday_of_iso_week, iter_weeks)  # noqa
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


def fetch_full_window(start_date: dt.date, end_date: dt.date) -> list[dict]:
    params = {"id": SERIES_ID, "cosd": start_date.isoformat(),
              "coed": end_date.isoformat()}
    url = f"{FRED_CSV_URL}?{urllib.parse.urlencode(params)}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    rdr = csv.DictReader(io.StringIO(r.text))
    return [dict(row) for row in rdr]


def index_by_date(rows: list[dict]) -> dict[dt.date, str]:
    out: dict[dt.date, str] = {}
    for r in rows:
        try:
            d = dt.date.fromisoformat(r["observation_date"])
        except (KeyError, ValueError):
            continue
        out[d] = r.get(SERIES_ID, ".")
    return out


def monday_observation(by_date: dict[dt.date, str], year: int,
                       week: int) -> tuple[dt.date, float] | None:
    """Return (observation_date, price) for the Monday of this ISO week.
    Falls back to the most recent prior weekday within the same ISO week
    if the Monday row is missing."""
    monday = monday_of_iso_week(year, week)
    # FRED stamps the observation_date as the Monday of the survey week.
    v = by_date.get(monday)
    if v not in (None, ".", ""):
        try:
            return monday, float(v)
        except ValueError:
            pass
    # Rare fallback: scan within the same ISO week for any value.
    for offset in range(1, 7):
        d = monday + dt.timedelta(days=offset)
        v = by_date.get(d)
        if v in (None, ".", ""):
            continue
        try:
            return d, float(v)
        except ValueError:
            continue
    return None


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)

    weeks = list(iter_weeks(args.start, args.end))
    if not weeks:
        print("[err]  empty week range", flush=True); return

    first_monday = weeks[0][2]
    last_monday  = weeks[-1][2]
    cosd = first_monday - dt.timedelta(days=7)
    coed = last_monday + dt.timedelta(days=6)

    if not args.force and all((TS_SOURCE / f"{week_label(m)}.json").exists()
                              for _, _, m in weeks):
        for _, _, m in weeks:
            print(f"[skip] {week_label(m)}", flush=True)
        return

    print(f"[fetch] FRED CSV id={SERIES_ID} cosd={cosd} coed={coed}", flush=True)
    rows = fetch_full_window(cosd, coed)
    by_date = index_by_date(rows)
    print(f"[fetch] received {len(rows)} weekly rows", flush=True)

    for y, w, monday in weeks:
        label = week_label(monday)
        path = TS_SOURCE / f"{label}.json"
        if path.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue
        result = monday_observation(by_date, y, w)
        if result is None:
            print(f"[empty] {label}: no GASDESW value in this ISO week",
                  flush=True); continue
        obs_date, price = result
        cat = classify(price)
        payload = {
            "iso_week":          label,
            "monday":            monday.isoformat(),
            "observation_date":  obs_date.isoformat(),
            "price_usd_per_gal": price,
            "diesel_price_band": cat,
            "raw_row": {
                "observation_date": obs_date.isoformat(),
                SERIES_ID:          f"{price}",
            },
        }
        path.write_text(json.dumps(payload, indent=2))
        print(f"[ok]   {label}: price=${price:.3f}/gal -> {cat} (obs={obs_date})",
              flush=True)


# --- step: gt ------------------------------------------------------------
def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    for y, w, monday in iter_weeks(args.start, args.end):
        label = week_label(monday)
        src = TS_SOURCE / f"{label}.json"
        dst = GT_SOURCE / f"{label}.json"
        if not src.exists():
            print(f"[skip] {label}: timeseries_source missing", flush=True); continue
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
