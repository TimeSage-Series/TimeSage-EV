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
import re
import sys
import time
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    TS_SOURCE, LANDING_BASE, ESMIS_BASE, HEADERS,
)
import datetime as dt
from _common import GT_SOURCE, LANDING_BASE, HEADERS  # noqa: E402


# --- step: timeseries ----------------------------------------------------

PDF_RE = re.compile(r"/sites/default/release-files/[^\"\']+/cost(\d{4})\.pdf")


def harvest_urls(pages: int) -> dict[str, str]:
    """Return mmyy -> absolute URL for every Cold Storage PDF found
    across the first `pages` pages of the landing list."""
    out: dict[str, str] = {}
    for p in range(pages):
        url = f"{LANDING_BASE}?items_per_page=10&page={p}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"[warn] page {p}: {e}", file=sys.stderr)
            continue
        for m in PDF_RE.finditer(r.text):
            mmyy = m.group(1)
            rel = m.group(0)
            absu = ESMIS_BASE + rel
            out.setdefault(mmyy, absu)
        time.sleep(0.3)
    return out


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    # 10 releases per page, newest first: the page budget has to grow as
    # releases accumulate or the oldest baseline months fall off the end.
    ap.add_argument("--pages", type=int, default=12)
    # The released corpus starts at February 2019 data (the March 2019
    # release); starting later changes the five-year baselines.
    ap.add_argument("--earliest-release", default="0319",
                    help="Earliest release MMYY to keep (default 0319 = Feb 2019 data).")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    urls = harvest_urls(args.pages)
    if not urls:
        print("[err] no PDF URLs harvested", file=sys.stderr)
        return 1
    print(f"[info] harvested {len(urls)} mmyy keys")

    def parse_mmyy(m: str) -> tuple[int, int]:
        mm = int(m[:2]); yy = int(m[2:])
        year = 2000 + yy if yy < 80 else 1900 + yy
        return year, mm

    earliest = parse_mmyy(args.earliest_release)
    keep = {m: u for m, u in urls.items() if parse_mmyy(m) >= earliest}
    print(f"[info] keeping {len(keep)} releases >= {args.earliest_release}")

    n_ok = 0
    n_skip = 0
    for mmyy, url in sorted(keep.items(), key=lambda kv: parse_mmyy(kv[0])):
        out = TS_SOURCE / f"cost{mmyy}.pdf"
        if out.exists() and not args.force:
            n_skip += 1
            continue
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            out.write_bytes(r.content)
            n_ok += 1
            print(f"[ok] {out.name} ({len(r.content):,} bytes)")
            time.sleep(0.4)
        except Exception as e:
            print(f"[warn] {mmyy} -> {url}: {e}", file=sys.stderr)
    print(f"[done] downloaded {n_ok}, skipped {n_skip}")
    return 0


# --- step: gt ------------------------------------------------------------
def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    out = GT_SOURCE / f"coldstorage-landing-{today}.html"
    if out.exists() and not args.force:
        print(f"[skip] {out.name} already exists; pass --force to re-download.")
        return 0
    r = requests.get(LANDING_BASE, headers=HEADERS, timeout=30)
    r.raise_for_status()
    out.write_text(r.text, encoding="utf-8")
    print(f"[ok] wrote {out} ({len(r.text):,} bytes)")
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
