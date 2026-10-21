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
import json
import sys
from pathlib import Path
import requests
import xlrd
sys.path.insert(0, str(Path(__file__).parent))
from _common import (TS_SOURCE, EIA_XLS_URL, SERIES_ID, classify,
                     week_label, friday_of_iso_week, iter_weeks,
                     excel_serial_to_date)  # noqa
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


def fetch_xls() -> bytes:
    r = requests.get(EIA_XLS_URL, timeout=60)
    r.raise_for_status()
    return r.content


def parse_xls(blob: bytes) -> dict[dt.date, float]:
    wb = xlrd.open_workbook(file_contents=blob)
    sh = wb.sheet_by_name("Data 1")
    out: dict[dt.date, float] = {}
    for i in range(3, sh.nrows):
        d_cell = sh.cell_value(i, 0)
        v_cell = sh.cell_value(i, 1)
        if d_cell == "" or v_cell == "":
            continue
        try:
            d = excel_serial_to_date(d_cell)
            v = float(v_cell)
        except (TypeError, ValueError):
            continue
        out[d] = v
    return out


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)

    weeks = list(iter_weeks(args.start, args.end))
    if not args.force and all((TS_SOURCE / f"{week_label(f)}.json").exists()
                              for _, _, f in weeks):
        for _, _, f in weeks:
            print(f"[skip] {week_label(f)}", flush=True)
        return

    print(f"[fetch] {EIA_XLS_URL}", flush=True)
    blob = fetch_xls()
    by_friday = parse_xls(blob)
    print(f"[fetch] parsed {len(by_friday)} Friday observations", flush=True)

    for y, w, friday in weeks:
        label = week_label(friday)
        path = TS_SOURCE / f"{label}.json"
        if path.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue
        pct = by_friday.get(friday)
        if pct is None:
            print(f"[empty] {label}: no reading for Friday {friday}",
                  flush=True); continue
        cat = classify(pct)
        payload = {
            "iso_week":                  label,
            "week_ending":               friday.isoformat(),
            "utilization_pct":           pct,
            "refinery_utilization_band": cat,
            "raw_row": {
                "week_ending":     friday.isoformat(),
                "utilization_pct": f"{pct}",
                "source":          SERIES_ID,
            },
        }
        path.write_text(json.dumps(payload, indent=2))
        print(f"[ok]   {label}: utilization={pct:.1f}% -> {cat}", flush=True)


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
