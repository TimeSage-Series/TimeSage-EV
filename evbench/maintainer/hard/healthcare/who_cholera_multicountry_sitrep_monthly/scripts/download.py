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
from _common import TS_SOURCE, GT_SOURCE, iter_months, month_label  # noqa
import time
import requests
from bs4 import BeautifulSoup
from _common import GT_SOURCE, WHO_HEADERS, iter_months, month_label  # noqa


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)

    months_with_gt = []
    months_missing_gt = []
    for y, m, _last in iter_months(args.start, args.end):
        label = month_label(y, m)
        if (GT_SOURCE / f"{label}.pdf").exists():
            months_with_gt.append(label)
        else:
            months_missing_gt.append(label)

    marker = TS_SOURCE / "_SOURCE_NOTE.json"
    marker.write_text(json.dumps({
        "note": (
            "Raw cholera timeseries fields are embedded in the same PDF as the GT. "
            "See ../gt_source/<YYYY-MNN>.pdf. Run `format.py timeseries` to extract "
            "structured fields (cumulative cases, deaths, CFR, MoM change, "
            "regional breakdown, WHO global risk level) into per-month JSON and "
            "the cumulative instance CSV."
        ),
        "months_available": months_with_gt,
        "months_missing": months_missing_gt,
    }, indent=2))
    print(f"timeseries_source/ marker written; {len(months_with_gt)} months "
          f"available in gt_source/, {len(months_missing_gt)} missing.")


# --- step: gt ------------------------------------------------------------
LANDING_PATH = Path(__file__).parent / "landing_urls.json"


# Filename tokens that mark a candidate as the _step_gt SitRep PDF.
SITREP_KEYWORDS = (
    "cholera",
    "situation-report",
    "sitrep",
    "epidemiological",
    "epidemiological_update",
)
# Reject obvious supplements / visualisations / annexes.
SITREP_BLACKLIST = (
    "visualisation",
    "visualization",
    "annex",
    "supplementary",
    "infographic",
    "dashboard",
    "map-",
    "maps-",
)


def resolve_pdf_url(landing_url: str) -> str | None:
    """Scrape the landing page and return the _step_gt SitRep PDF download URL."""
    r = requests.get(landing_url, headers=WHO_HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    candidates: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        href_lc = href.lower()
        # WHO sometimes appends ?sfvrsn=... and ?download=true to PDF links
        if ".pdf" not in href_lc:
            continue
        if any(b in href_lc for b in SITREP_BLACKLIST):
            continue
        if any(k in href_lc for k in SITREP_KEYWORDS):
            candidates.append(href)

    if not candidates:
        # Last resort: any non-blacklisted PDF link
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if ".pdf" in href.lower() and not any(b in href.lower() for b in SITREP_BLACKLIST):
                candidates.append(href)
                break

    if not candidates:
        return None

    pdf = candidates[0]
    if pdf.startswith("//"):
        pdf = "https:" + pdf
    elif pdf.startswith("/"):
        pdf = "https://www.who.int" + pdf
    return pdf


def fetch_pdf(pdf_url: str) -> bytes:
    r = requests.get(pdf_url, headers=WHO_HEADERS, timeout=180)
    r.raise_for_status()
    return r.content


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MNN inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-MNN inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    landing_data = json.loads(LANDING_PATH.read_text())
    landings = landing_data["landing_urls"]
    known_missing = set(landing_data.get("missing_months_known", []))

    for y, m, _last in iter_months(args.start, args.end):
        label = month_label(y, m)
        path = GT_SOURCE / f"{label}.pdf"
        if path.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue
        if label in known_missing:
            print(f"[gap]  {label}: known WHO publication gap", flush=True); continue
        if label not in landings:
            print(f"[miss] {label}: no landing URL in landing_urls.json", flush=True); continue
        try:
            pdf_url = resolve_pdf_url(landings[label])
            if pdf_url is None:
                print(f"[err]  {label}: landing page has no PDF link", flush=True); continue
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
