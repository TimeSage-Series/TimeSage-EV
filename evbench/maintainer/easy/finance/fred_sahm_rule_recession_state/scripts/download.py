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
import io
import json
import sys
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from _common import (TS_SOURCE, FRED_CSV_URL, SERIES_ID, classify,
                     month_label, iter_months, parse_month_label,
                     first_of_month)  # noqa
import shutil
from _common import TS_SOURCE, GT_SOURCE, month_label, iter_months  # noqa

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


def fetch_csv(start_iso: str, end_iso: str) -> str:
    """Pull the full FRED CSV for SAHMCURRENT between two ISO dates."""
    params = {"id": SERIES_ID, "cosd": start_iso, "coed": end_iso}
    r = requests.get(FRED_CSV_URL, params=params, timeout=60)
    r.raise_for_status()
    return r.text


def parse_csv(text: str) -> dict[str, float]:
    """Parse FRED CSV → {observation_date(YYYY-MM-DD): value(float)}.

    FRED uses '.' as the missing-value marker.
    """
    out: dict[str, float] = {}
    rdr = csv.reader(io.StringIO(text))
    header = next(rdr, None)
    if not header or header[0].lower() not in ("observation_date", "date"):
        raise ValueError(f"Unexpected FRED CSV header: {header!r}")
    for row in rdr:
        if len(row) < 2:
            continue
        date, raw = row[0].strip(), row[1].strip()
        if raw in ("", "."):
            continue
        try:
            out[date] = float(raw)
        except ValueError:
            continue
    return out


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MNN inclusive (e.g. 2024-M05)")
    ap.add_argument("--end",   required=True, help="YYYY-MNN inclusive (e.g. 2026-M04)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)

    y0, m0 = parse_month_label(args.start)
    y1, m1 = parse_month_label(args.end)
    start_iso = first_of_month(y0, m0).isoformat()
    # The end of the FRED query window is the first-of-end-month (inclusive).
    end_iso = first_of_month(y1, m1).isoformat()

    print(f"[fetch] FRED {SERIES_ID} {start_iso} -> {end_iso}", flush=True)
    text = fetch_csv(start_iso, end_iso)
    data = parse_csv(text)
    print(f"[fetch] {len(data)} observations parsed", flush=True)

    for y, m, d in iter_months(args.start, args.end):
        label = month_label(y, m)
        path = TS_SOURCE / f"{label}.json"
        if path.exists() and not args.force:
            print(f"[skip] {label}", flush=True)
            continue
        iso = d.isoformat()
        if iso not in data:
            print(f"[empty] {label}: no FRED row for {iso} (not published yet?)", flush=True)
            continue
        value = data[iso]
        cat = classify(value)
        payload = {
            "month_label":      label,
            "observation_date": iso,
            "series_id":        SERIES_ID,
            "value":            value,
            "category":         cat,
        }
        path.write_text(json.dumps(payload, indent=2))
        print(f"[ok]   {label}: value={value:.2f} category={cat}", flush=True)


# --- step: gt ------------------------------------------------------------
def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MNN inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-MNN inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)

    for y, m, _ in iter_months(args.start, args.end):
        label = month_label(y, m)
        src = TS_SOURCE / f"{label}.json"
        dst = GT_SOURCE / f"{label}.json"
        if not src.exists():
            print(f"[skip] {label}: timeseries_source missing — run `download.py timeseries` first",
                  flush=True)
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
