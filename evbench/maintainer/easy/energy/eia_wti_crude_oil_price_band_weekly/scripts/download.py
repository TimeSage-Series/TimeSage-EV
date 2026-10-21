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
                     week_label, friday_of_iso_week, iter_weeks)  # noqa
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
    """Fetch the FRED CSV for [start_date, end_date] inclusive. Returns
    list of {"observation_date": "YYYY-MM-DD", "VIXCLS": "<value>"}."""
    params = {
        "id":   SERIES_ID,
        "cosd": start_date.isoformat(),
        "coed": end_date.isoformat(),
    }
    url = f"{FRED_CSV_URL}?{urllib.parse.urlencode(params)}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    rdr = csv.DictReader(io.StringIO(r.text))
    return [dict(row) for row in rdr]


def index_by_date(rows: list[dict]) -> dict[dt.date, str]:
    """Index FRED CSV rows by observation_date. Missing values come back
    as '.' from FRED — caller is responsible for handling them."""
    out: dict[dt.date, str] = {}
    for r in rows:
        d = dt.date.fromisoformat(r["observation_date"])
        out[d] = r.get(SERIES_ID, ".")
    return out


def friday_close_for_week(by_date: dict[dt.date, str],
                          year: int, week: int) -> tuple[dt.date, float] | None:
    """Return (date, vix_close) for the Friday of this ISO week, or the
    nearest prior weekday in the same ISO week if Friday is missing.
    Returns None if no valid value exists in the week."""
    friday = friday_of_iso_week(year, week)
    # Walk Friday → Thursday → ... → Monday looking for a real value.
    for offset in range(0, 5):
        d = friday - dt.timedelta(days=offset)
        v = by_date.get(d)
        if v is None or v == "." or v == "":
            continue
        try:
            return d, float(v)
        except ValueError:
            continue
    return None


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-Www inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-Www inclusive")
    ap.add_argument("--force", action="store_true",
                    help="Re-download even if files already exist.")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)

    # Compute the full daily window. Add a small left buffer so that if
    # Friday of the first ISO week is a holiday we can still backfill
    # from earlier days inside the same week.
    weeks = list(iter_weeks(args.start, args.end))
    if not weeks:
        print("[err]  empty week range", flush=True)
        return
    first_friday = weeks[0][2]
    last_friday  = weeks[-1][2]
    # Buffer: 7 calendar days back, 0 forward (we never need future).
    cosd = first_friday - dt.timedelta(days=7)
    coed = last_friday

    # If everything already exists and --force is not set, short-circuit.
    if not args.force and all((TS_SOURCE / f"{week_label(f)}.json").exists()
                              for _, _, f in weeks):
        for _, _, f in weeks:
            print(f"[skip] {week_label(f)}", flush=True)
        return

    print(f"[fetch] FRED CSV id={SERIES_ID} cosd={cosd} coed={coed}", flush=True)
    rows = fetch_full_window(cosd, coed)
    by_date = index_by_date(rows)
    print(f"[fetch] received {len(rows)} daily rows", flush=True)

    for y, w, friday in weeks:
        label = week_label(friday)
        path = TS_SOURCE / f"{label}.json"
        if path.exists() and not args.force:
            print(f"[skip] {label}", flush=True)
            continue
        result = friday_close_for_week(by_date, y, w)
        if result is None:
            print(f"[empty] {label}: no VIX value in this ISO week", flush=True)
            continue
        obs_date, vix = result
        cat = classify(vix)
        payload = {
            "iso_week":  label,
            "friday":    friday.isoformat(),
            "obs_date":  obs_date.isoformat(),
            "vix_close": vix,
            "category":  cat,
            "raw_row": {
                "observation_date": obs_date.isoformat(),
                SERIES_ID:           f"{vix}",
            },
        }
        path.write_text(json.dumps(payload, indent=2))
        print(f"[ok]   {label}: vix={vix:.2f} category={cat} "
              f"(obs={obs_date})", flush=True)


# --- step: gt ------------------------------------------------------------
def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)

    for y, w, friday in iter_weeks(args.start, args.end):
        label = week_label(friday)
        src = TS_SOURCE / f"{label}.json"
        dst = GT_SOURCE / f"{label}.json"
        if not src.exists():
            print(f"[skip] {label}: timeseries_source missing — run "
                  f"`download.py timeseries` first", flush=True)
            continue
        if dst.exists() and not args.force:
            print(f"[skip] {label}", flush=True)
            continue
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
