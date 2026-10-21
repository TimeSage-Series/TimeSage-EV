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
from _common import TS_SOURCE, GT_SOURCE, iter_meetings  # noqa: E402
import datetime as dt
import time
import requests
from bs4 import BeautifulSoup
from _common import GT_SOURCE, BOE_HEADERS, iter_meetings, pdf_filename  # noqa: E402


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)

    meetings_with_gt = []
    meetings_missing_gt = []
    for label, _d in iter_meetings(args.start, args.end):
        if (GT_SOURCE / f"{label}.pdf").exists():
            meetings_with_gt.append(label)
        else:
            meetings_missing_gt.append(label)

    marker = TS_SOURCE / "_SOURCE_NOTE.json"
    marker.write_text(json.dumps({
        "note": (
            "Raw BoE monetary-policy timeseries fields are embedded in the same "
            "PDF as the GT. See ../gt_source/<label>.pdf. Run `format.py timeseries` "
            "to extract structured fields (bank_rate_decision, current_bank_rate_pct, "
            "mpc_vote) into per-meeting JSON and the cumulative instance CSV."
        ),
        "meetings_available": meetings_with_gt,
        "meetings_missing":   meetings_missing_gt,
    }, indent=2))
    print(f"timeseries_source/ marker written; {len(meetings_with_gt)} meetings "
          f"available in gt_source/, {len(meetings_missing_gt)} missing.")


# --- step: gt ------------------------------------------------------------
LANDING_PATH = Path(__file__).parent / "landing_urls.json"


# Filename tokens that mark a candidate as the _step_gt Monetary Policy Summary
# and Minutes PDF. The BoE also publishes a separate Monetary Policy Report
# (longer, quarterly) and supplementary visualisations; these are excluded.
MPS_KEYWORDS = (
    "monetary-policy-summary-and-minutes",
)
MPS_BLACKLIST = (
    "monetary-policy-report",      # quarterly companion report, different doc
    "visualisation",
    "visualization",
    "supplementary",
    "infographic",
    "dashboard",
    "press-conference",
    "transcript",
)


def resolve_pdf_url(landing_url: str) -> str | None:
    """Scrape the landing page and return the canonical PDF URL."""
    r = requests.get(landing_url, headers=BOE_HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    candidates: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        href_lc = href.lower()
        # BoE PDF links may be ``.pdf`` or ``.ashx?... .pdf`` style.
        if ".pdf" not in href_lc and ".ashx" not in href_lc:
            continue
        if any(b in href_lc for b in MPS_BLACKLIST):
            continue
        if any(k in href_lc for k in MPS_KEYWORDS):
            candidates.append(href)

    if not candidates:
        # Last-resort: take the first non-blacklisted PDF on the page.
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ".pdf" in href.lower() and not any(b in href.lower() for b in MPS_BLACKLIST):
                candidates.append(href); break

    if not candidates:
        return None

    pdf = candidates[0]
    if pdf.startswith("//"):
        pdf = "https:" + pdf
    elif pdf.startswith("/"):
        pdf = "https://www.bankofengland.co.uk" + pdf
    return pdf


def canonical_pdf_url(d: dt.date) -> str:
    """The canonical /-/media/.../monetary-policy-summary-and-minutes-<month>-<YYYY>.pdf URL."""
    return (
        f"https://www.bankofengland.co.uk/-/media/boe/files/monetary-policy-summary-and-minutes/"
        f"{d.year}/{pdf_filename(d)}.pdf"
    )


def fetch_pdf(pdf_url: str) -> bytes:
    r = requests.get(pdf_url, headers=BOE_HEADERS, timeout=180)
    r.raise_for_status()
    return r.content


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD or YYYY-MonthDD label, inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-MM-DD or YYYY-MonthDD label, inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    landing_data = json.loads(LANDING_PATH.read_text())
    landings = landing_data["landing_urls"]
    known_missing = set(landing_data.get("missing_months_known", []))

    for label, d in iter_meetings(args.start, args.end):
        path = GT_SOURCE / f"{label}.pdf"
        if path.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue
        if label in known_missing:
            print(f"[gap]  {label}: known publication gap", flush=True); continue

        # Strategy: try the landing-page resolver first (handles future
        # filename changes), then fall back to the canonical URL.
        pdf_url: str | None = None
        if label in landings:
            try:
                pdf_url = resolve_pdf_url(landings[label])
            except requests.HTTPError as e:
                print(f"[warn] {label}: landing fetch failed ({e}); will try canonical URL", flush=True)
        if pdf_url is None:
            pdf_url = canonical_pdf_url(d)

        try:
            content = fetch_pdf(pdf_url)
            path.write_bytes(content)
            print(f"[ok]   {label}: {len(content):,} bytes -> {pdf_url.split('/')[-1].split('?')[0]}",
                  flush=True)
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
