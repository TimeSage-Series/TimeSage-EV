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
from pathlib import Path
import argparse
import sys
import urllib.request
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    GT_SOURCE, HEADERS, TS_SOURCE,
    iter_months, mer_archive_pdf_url, month_label,
)


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> None:
    root = Path(__file__).resolve().parents[1]
    print(f"Source artifacts are checked in under {root / 'timeseries_source'}")


# --- step: gt ------------------------------------------------------------
TABLES = ["T01.01", "T01.03", "T03.01", "T04.01", "T06.01", "T07.02A"]


def fetch(url: str, dest: Path, refresh: bool = False) -> bool:
    if dest.exists() and dest.stat().st_size > 5000 and not refresh:
        return False
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        print(f"[err] {dest.name}: HTTP {e.code} for {url}", file=sys.stderr)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-start", default="2024-04")
    ap.add_argument("--release-end", default="2026-03")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--skip-pdfs", action="store_true",
                    help="Skip per-release MER PDFs (use when CSV ingest only).")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    TS_SOURCE.mkdir(parents=True, exist_ok=True)

    # 1) Per-table CSV bundles.
    print("== timeseries CSV tables ==")
    for tbl in TABLES:
        url = f"https://www.eia.gov/totalenergy/data/browser/csv.php?tbl={tbl}"
        dest = TS_SOURCE / f"mer_{tbl}.csv"
        if fetch(url, dest, refresh=args.refresh):
            print(f"[ok]   {dest.name} ({dest.stat().st_size} bytes)")
        else:
            print(f"[skip] {dest.name} already present")

    # 2) Per-release MER PDFs.
    if not args.skip_pdfs:
        print("== per-release MER PDFs ==")
        for d in iter_months(args.release_start, args.release_end):
            release = month_label(d)
            url = mer_archive_pdf_url(release)
            dest = GT_SOURCE / f"mer_{release}.pdf"
            if fetch(url, dest, refresh=args.refresh):
                print(f"[ok]   mer_{release}.pdf ({dest.stat().st_size} bytes)")
            else:
                if dest.exists() and dest.stat().st_size > 5000:
                    print(f"[skip] mer_{release}.pdf already present")
                else:
                    print(f"[miss] mer_{release}.pdf")

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
