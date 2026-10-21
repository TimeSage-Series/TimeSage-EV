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
import sys
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, GT_SOURCE, iter_months, month_label  # noqa
import argparse, sys, time
import requests
from _common import GT_SOURCE, EIA_HEADERS, EIA_NGM_URL_TPL, iter_months, month_label  # noqa


# --- step: timeseries ----------------------------------------------------


def _step_timeseries():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    args = ap.parse_args()
    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    avail = [month_label(y, m) for y, m, _ in iter_months(args.start, args.end)
             if (GT_SOURCE / f"{month_label(y, m)}.pdf").exists()]
    miss = [month_label(y, m) for y, m, _ in iter_months(args.start, args.end)
            if not (GT_SOURCE / f"{month_label(y, m)}.pdf").exists()]
    (TS_SOURCE / "_SOURCE_NOTE.json").write_text(json.dumps({
        "note": "Raw NG monthly data is embedded in the same PDF as the GT.",
        "months_available": avail, "months_missing": miss,
    }, indent=2))
    print(f"timeseries_source/ marker; {len(avail)} months available, {len(miss)} missing.")


# --- step: gt ------------------------------------------------------------
def _step_gt():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    for y, m, _ in iter_months(args.start, args.end):
        label = month_label(y, m)
        path = GT_SOURCE / f"{label}.pdf"
        if path.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue
        url = EIA_NGM_URL_TPL.format(y=y, mm=m)
        try:
            r = requests.get(url, headers=EIA_HEADERS, timeout=60)
            if r.status_code == 200:
                path.write_bytes(r.content)
                print(f"[ok]   {label}: {len(r.content):,} bytes", flush=True)
            else:
                print(f"[err]  {label}: status {r.status_code}", flush=True)
        except Exception as e:
            print(f"[err]  {label}: {e}", flush=True)
        time.sleep(0.4)

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
