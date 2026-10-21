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
from _common import TS_SOURCE, GT_SOURCE, iter_biweekly_issues, biweekly_label  # noqa
import time
import requests
from bs4 import BeautifulSoup
from _common import GT_SOURCE, PAHO_HEADERS, iter_biweekly_issues, biweekly_label  # noqa


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)

    issues_with_gt = []
    issues_missing_gt = []
    for y, w1, w2, _sat in iter_biweekly_issues(args.start, args.end):
        label = biweekly_label(y, w1, w2)
        if (GT_SOURCE / f"{label}.pdf").exists():
            issues_with_gt.append(label)
        else:
            issues_missing_gt.append(label)

    marker = TS_SOURCE / "_SOURCE_NOTE.json"
    marker.write_text(json.dumps({
        "note": (
            "Raw measles/rubella per-country timeseries data is embedded in "
            "the same PDF as the GT. See ../gt_source/<YYYY-Www1-w2>.pdf. Run "
            "`format.py timeseries` to extract structured fields (confirmed "
            "measles cases per country, total, leading country) into "
            "per-issue JSON."
        ),
        "issues_available": issues_with_gt,
        "issues_missing": issues_missing_gt,
    }, indent=2))
    print(f"timeseries_source/ marker written; {len(issues_with_gt)} issues "
          f"available in gt_source/, {len(issues_missing_gt)} missing.")


# --- step: gt ------------------------------------------------------------
LANDING_PATH = Path(__file__).parent / "landing_urls.json"


def resolve_pdf_url(landing_url: str) -> str | None:
    """Scrape the landing page and return the _step_gt bulletin PDF URL.

    Heuristic: the first ``<a href=...>`` ending in ``.pdf`` whose href
    contains ``sme`` or ``measles`` (case-insensitive). PAHO uses ``sme``
    as the recurring slug for surveillance-measles-epidemiology files.
    """
    r = requests.get(landing_url, headers=PAHO_HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    candidates: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        href_lc = href.lower()
        if not href_lc.endswith(".pdf"):
            continue
        if "sme" in href_lc or "measles" in href_lc:
            candidates.append(href)
    if not candidates:
        # Fallback: any PDF link at all.
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().endswith(".pdf"):
                candidates.append(href)
                break
    if not candidates:
        return None
    pdf = candidates[0]
    if pdf.startswith("/"):
        pdf = "https://www.paho.org" + pdf
    return pdf


def fetch_pdf(pdf_url: str) -> bytes:
    r = requests.get(pdf_url, headers=PAHO_HEADERS, timeout=120)
    r.raise_for_status()
    return r.content


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True,
                    help="YYYY-Www1-w2 inclusive (e.g. 2025-W01-02)")
    ap.add_argument("--end",   required=True,
                    help="YYYY-Www1-w2 inclusive (e.g. 2026-W15-16)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    landing_data = json.loads(LANDING_PATH.read_text())
    landings = landing_data["landing_urls"]

    for y, w1, w2, _sat in iter_biweekly_issues(args.start, args.end):
        label = biweekly_label(y, w1, w2)
        path = GT_SOURCE / f"{label}.pdf"
        if path.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue
        if label not in landings:
            print(f"[miss] {label}: no landing URL in landing_urls.json", flush=True); continue
        try:
            pdf_url = resolve_pdf_url(landings[label])
            if pdf_url is None:
                print(f"[err]  {label}: landing page has no PDF link", flush=True); continue
            content = fetch_pdf(pdf_url)
            path.write_bytes(content)
            print(f"[ok]   {label}: {len(content):,} bytes -> {pdf_url.split('/')[-1]}", flush=True)
        except requests.HTTPError as e:
            print(f"[err]  {label}: {e}", flush=True)
        except requests.RequestException as e:
            print(f"[err]  {label}: {e}", flush=True)
        time.sleep(0.8)

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
