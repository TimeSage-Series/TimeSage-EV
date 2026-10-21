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
from _common import TS_SOURCE, GT_SOURCE, label_from_date, iter_meetings  # noqa
import time
import requests
from bs4 import BeautifulSoup
from _common import GT_SOURCE, ECB_HEADERS, label_from_date, iter_meetings  # noqa


# --- step: timeseries ----------------------------------------------------

LANDING_PATH = Path(__file__).parent / "landing_urls.json"


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None)
    ap.add_argument("--end",   default=None)
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    landing_data = json.loads(LANDING_PATH.read_text())
    meetings = landing_data["meeting_dates"]

    with_gt, missing_gt = [], []
    for d in iter_meetings(meetings, args.start, args.end):
        label = label_from_date(d)
        if (GT_SOURCE / f"{label}.pdf").exists():
            with_gt.append(label)
        else:
            missing_gt.append(label)

    marker = TS_SOURCE / "_SOURCE_NOTE.json"
    marker.write_text(json.dumps({
        "note": (
            "Raw ECB rate-decision / deposit-facility-rate fields are embedded "
            "in the same PDF as the GT. See ../gt_source/<YYYY-MmonDD>.pdf. "
            "Run `format.py timeseries` to extract structured fields "
            "(rate_decision, deposit_facility_rate_pct, inflation/growth/risk "
            "assessment text) into per-meeting JSON and the cumulative instance CSV."
        ),
        "meetings_available": with_gt,
        "meetings_missing":   missing_gt,
    }, indent=2))
    print(f"timeseries_source/ marker written; {len(with_gt)} meetings "
          f"available in gt_source/, {len(missing_gt)} missing.")


# --- step: gt ------------------------------------------------------------
def resolve_pdf_url(landing_url: str) -> str | None:
    """Scrape the ECB landing page and return the absolute PDF URL.

    We look for <a href> matching '/shared/pdf/ecb.ds' (the canonical
    Combined-statement PDF prefix). Falls back to any '.en.pdf' link
    containing 'ecb.ds' if the primary anchor is absent.
    """
    r = requests.get(landing_url, headers=ECB_HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    primary: list[str] = []
    fallback: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        href_lc = href.lower()
        if not href_lc.endswith(".pdf") and ".pdf" not in href_lc:
            continue
        if "/shared/pdf/ecb.ds" in href_lc and href_lc.endswith(".en.pdf"):
            primary.append(href)
        elif "ecb.ds" in href_lc and href_lc.endswith(".en.pdf"):
            fallback.append(href)

    candidates = primary or fallback
    if not candidates:
        return None

    pdf = candidates[0]
    if pdf.startswith("//"):
        pdf = "https:" + pdf
    elif pdf.startswith("/"):
        pdf = "https://www.ecb.europa.eu" + pdf
    return pdf


def fetch_pdf(pdf_url: str) -> bytes:
    r = requests.get(pdf_url, headers=ECB_HEADERS, timeout=180)
    r.raise_for_status()
    return r.content


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None, help="meeting label, e.g. 2023-Jun15")
    ap.add_argument("--end",   default=None, help="meeting label, e.g. 2026-Apr30")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    landing_data = json.loads(LANDING_PATH.read_text())
    landings = landing_data["landing_urls"]
    meetings = landing_data["meeting_dates"]

    for d in iter_meetings(meetings, args.start, args.end):
        label = label_from_date(d)
        iso = d.isoformat()
        out = GT_SOURCE / f"{label}.pdf"
        if out.exists() and not args.force:
            print(f"[skip] {label}", flush=True)
            continue
        if iso not in landings:
            print(f"[miss] {label}: no landing URL", flush=True)
            continue
        try:
            pdf_url = resolve_pdf_url(landings[iso])
            if pdf_url is None:
                print(f"[err]  {label}: landing has no ecb.ds PDF link", flush=True)
                continue
            content = fetch_pdf(pdf_url)
            out.write_bytes(content)
            tail = pdf_url.split("/")[-1].split("?")[0]
            print(f"[ok]   {label}: {len(content):,} bytes -> {tail}", flush=True)
        except requests.HTTPError as e:
            print(f"[err]  {label}: {e}", flush=True)
        time.sleep(1.0)

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
