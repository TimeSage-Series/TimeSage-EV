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
from _parser import parse_ngw  # noqa
import time
import requests
from _common import GT_SOURCE, HEADERS, url_for  # noqa


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    htmls = sorted(GT_SOURCE.glob("*.html"))
    if not htmls:
        raise SystemExit("[error] no HTML in gt_source/")
    n_ok = n_err = 0
    for h in htmls:
        label = h.stem
        out = TS_SOURCE / f"{label}.json"
        if out.exists() and not args.force:
            print(f"[skip] {label}"); n_ok += 1; continue
        try:
            parsed = parse_ngw(h)
        except Exception as e:
            print(f"[err]  {label}: {e}"); n_err += 1; continue
        out.write_text(json.dumps(parsed, indent=2))
        hh_cur = parsed.get("henry_hub_this_wed")
        hh_change = parsed.get("henry_hub_change_dollar")
        print(f"[ok]   {label}: henry_hub_this_wed=${hh_cur} change=${hh_change} "
              f"highlights_chars={len(parsed.get('highlights_verbatim', ''))}")
        n_ok += 1
    print(f"\n=== ok={n_ok} err={n_err} ===")
    return 0 if n_err == 0 else 1


# --- step: gt ------------------------------------------------------------
LANDING = Path(__file__).parent / "landing_urls.json"


def fetch(url: str) -> bytes:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    if b"Natural Gas Weekly Update" not in r.content and b"Highlights" not in r.content:
        raise RuntimeError(f"unexpected content for {url}")
    return r.content


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    landing = json.loads(LANDING.read_text())
    verified = []; missing = []
    for label in landing["candidate_dates"]:
        out = GT_SOURCE / f"{label}.html"
        if out.exists() and not args.force:
            verified.append(label); print(f"[skip] {label}"); continue
        url = url_for(label)
        try:
            out.write_bytes(fetch(url))
            verified.append(label)
            print(f"[ok]   {label}: {out.stat().st_size:,} bytes")
        except Exception as e:
            missing.append({"date": label, "url": url, "reason": str(e)})
            print(f"[err]  {label}: {e}")
        time.sleep(0.5)
    (GT_SOURCE / "_verified.json").write_text(json.dumps({
        "verified_dates": sorted(verified), "missing": missing,
        "count_verified": len(verified),
    }, indent=2))
    print(f"\n=== verified={len(verified)} missing={len(missing)} ===")
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
