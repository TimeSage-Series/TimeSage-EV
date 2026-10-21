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
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE, TS_SOURCE  # noqa
from _html_parser import parse_html  # noqa
import time
import requests
from _common import GT_SOURCE, HEADERS, iter_months, month_label, html_url_for  # noqa


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    files = sorted(GT_SOURCE.glob("*.html"))
    if not files:
        raise SystemExit("[error] no HTML in gt_source/")
    n_ok = n_err = 0
    for f in files:
        label = f.stem
        out = TS_SOURCE / f"{label}.json"
        if out.exists() and not args.force:
            print(f"[skip] {label}"); n_ok += 1; continue
        try:
            parsed = parse_html(f)
        except Exception as e:
            print(f"[err]  {label}: {e}"); n_err += 1; continue
        out.write_text(json.dumps(parsed, indent=2))
        print(f"[ok]   {label}: ga={parsed['general_activity_index_current']} "
              f"dir={parsed['direction']} prod={parsed['production_index_current']}")
        n_ok += 1
    print(f"\n=== ok={n_ok} err={n_err} ===")
    return 0 if n_err == 0 else 1


# --- step: gt ------------------------------------------------------------
def fetch(url: str) -> bytes:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    # Sanity: real report has 'Texas factory' / 'production index' somewhere
    if b"production index" not in r.content and b"Texas" not in r.content:
        raise RuntimeError(f"missing TMOS content markers at {url}")
    return r.content


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM")
    ap.add_argument("--end",   required=True, help="YYYY-MM")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    ok = []; bad = []
    for y, m in iter_months(args.start, args.end):
        label = month_label(y, m)
        path = GT_SOURCE / f"{label}.html"
        if path.exists() and not args.force:
            ok.append(label); print(f"[skip] {label}"); continue
        url = html_url_for(y, m)
        try:
            path.write_bytes(fetch(url))
            ok.append(label)
            print(f"[ok]   {label}: {path.stat().st_size:,} bytes")
        except Exception as e:
            bad.append({"period": label, "url": url, "reason": str(e)})
            print(f"[err]  {label}: {e}")
        time.sleep(0.3)
    (GT_SOURCE / "_verified.json").write_text(json.dumps({
        "verified_periods": sorted(ok), "missing": bad, "count_verified": len(ok),
    }, indent=2))
    print(f"\n=== verified={len(ok)} missing={len(bad)} ===")
    return 0

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
