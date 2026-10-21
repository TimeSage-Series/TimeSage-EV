#!/usr/bin/env python3
"""Download this scenario's source artifacts.

    python scripts/download.py                 # every step, in order: gt -> timeseries
    python scripts/download.py gt            # one step
    python scripts/download.py timeseries [flags]    # …with that step's own flags
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
from _common import GT_SOURCE, TS_SOURCE  # noqa: E402
from _pdf_parser import parse_pdf  # noqa: E402
import re
import time
import requests
from _common import (  # noqa: E402
    GT_SOURCE, LANDING_BASE, ESMIS_BASE, HEADERS, SERIES_FIRST,
    mmyy_to_release_month, release_month_to_folder,
)


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(GT_SOURCE.glob("*.pdf"))
    if not pdfs:
        raise SystemExit("[error] no PDFs in gt_source/ -- run `download.py gt` first")
    n_ok = n_err = 0
    for pdf in pdfs:
        label = pdf.stem  # YYYY-MM
        out = TS_SOURCE / f"{label}.json"
        if out.exists() and not args.force:
            print(f"[skip] {label}", flush=True); n_ok += 1; continue
        parsed = parse_pdf(pdf)
        if parsed is None:
            print(f"[err]  {label}: placements regex did not match", flush=True)
            n_err += 1; continue
        out.write_text(json.dumps(parsed, indent=2))
        print(f"[ok]   {label}: {parsed['placements_million']:.2f}M head, "
              f"{parsed['yoy_pct_magnitude']:.0f}% {parsed['yoy_direction_raw']} "
              f"{parsed['prior_year']} -> {parsed['placements_yoy_class']}", flush=True)
        n_ok += 1
    print(f"\n=== ok={n_ok} err={n_err} ===")
    return 0 if n_err == 0 else 1


# --- step: gt ------------------------------------------------------------
HREF_RX = re.compile(r'href="(?P<path>[^"]*cofd(?P<mmyy>[0-9]{4})\.pdf)"')


def harvest_pages(max_pages: int) -> dict[str, str]:
    """Return mapping MMYY -> absolute URL across pages 0..max_pages-1."""
    out: dict[str, str] = {}
    for page in range(max_pages):
        url = f"{LANDING_BASE}?page={page}"
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"[warn] page={page} HTTP {r.status_code}; stopping pagination",
                  file=sys.stderr)
            break
        found_on_page = 0
        for m in HREF_RX.finditer(r.text):
            mmyy = m.group("mmyy")
            path = m.group("path")
            if not path.startswith("http"):
                path = ESMIS_BASE + path
            # Prefer the FIRST occurrence per MMYY (esmis lists newest at top).
            out.setdefault(mmyy, path)
            found_on_page += 1
        print(f"[ok]   page={page}: {found_on_page} cofd refs harvested "
              f"(cum unique MMYY: {len(out)})", flush=True)
        if found_on_page == 0:
            break
        time.sleep(0.5)
    return out


def fetch_pdf(url: str) -> bytes:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise RuntimeError(f"not-a-pdf: {url}")
    return r.content


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    # The landing page lists newest first, so a fixed page budget silently
    # drops the oldest releases as new ones arrive (2022-12..2023-02 were lost
    # this way). Pagination stops at the first empty page, so be generous.
    ap.add_argument("--max-pages", type=int, default=20)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    mmyy_to_url = harvest_pages(args.max_pages)
    if not mmyy_to_url:
        raise SystemExit("[error] no cofd PDFs harvested from landing pages")

    manifest = {}
    for mmyy, url in sorted(mmyy_to_url.items()):
        year, month = mmyy_to_release_month(mmyy)
        label = release_month_to_folder(year, month)
        if label < SERIES_FIRST:
            continue
        out = GT_SOURCE / f"{label}.pdf"
        if out.exists() and not args.force:
            manifest[label] = {"url": url, "path": str(out.relative_to(GT_SOURCE.parent))}
            print(f"[skip] {label}: already on disk", flush=True); continue
        try:
            out.write_bytes(fetch_pdf(url))
            manifest[label] = {"url": url, "path": str(out.relative_to(GT_SOURCE.parent))}
            print(f"[ok]   {label}: {out.stat().st_size:,} bytes  <-  {url}", flush=True)
        except Exception as e:
            print(f"[err]  {label}: {e}", flush=True)
        time.sleep(0.4)

    (GT_SOURCE / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\n=== downloaded {len(manifest)} unique monthly PDFs ===", flush=True)
    return 0

# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------

#: Execution order. This scenario builds the series from the ground truth, so gt runs first.
STEPS = ("gt", "timeseries")

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
