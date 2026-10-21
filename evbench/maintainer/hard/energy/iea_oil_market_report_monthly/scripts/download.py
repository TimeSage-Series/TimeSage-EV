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
from _common import GT_SOURCE, TS_SOURCE, iter_months, month_label  # noqa: E402
import re
import time
import requests
from bs4 import BeautifulSoup
from _common import GT_SOURCE, IEA_HEADERS, iter_months, month_label  # noqa: E402


# --- step: timeseries ----------------------------------------------------

LANDING_PATH = Path(__file__).parent / "landing_urls.json"


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM inclusive")
    ap.add_argument("--end",   required=True, help="YYYY-MM inclusive")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    data = json.loads(LANDING_PATH.read_text())
    landings = data["landing_urls"]

    have, missing = [], []
    for d in iter_months(args.start, args.end):
        label = month_label(d)
        if label not in landings:
            continue
        if (GT_SOURCE / f"{label}.pdf").exists():
            have.append(label)
        else:
            missing.append(label)

    marker = TS_SOURCE / "_SOURCE_NOTE.json"
    marker.write_text(json.dumps({
        "note": (
            "IEA OMR numeric/categorical fields are embedded in the same PDF "
            "as the GT artifact. See ../gt_source/<label>.pdf. Run "
            "`format.py timeseries` to extract per-issue JSON and build the "
            "cumulative instance CSV."
        ),
        "extracted_fields": [
            "global_demand_mbd_latest",
            "global_supply_mbd_latest",
            "oecd_stocks_million_bbl",
            "key_drivers_text",
            "risks_text",
            "outlook_text",
            "highlights_summary_text",
        ],
        "issues_available": have,
        "issues_missing": missing,
    }, indent=2))
    print(f"timeseries_source/ marker written; {len(have)} issues available, "
          f"{len(missing)} missing.", flush=True)


# --- step: gt ------------------------------------------------------------
# Match any asset path under iea.blob.core.windows.net/assets/... that names
# an OilMarketReport PDF. The leading hyphen in -<DD><MON><YYYY>_... is part
# of the IEA convention; we accept any URL containing both 'OilMarketReport'
# and ending in .pdf within the IEA blob storage host.
PDF_RX = re.compile(
    r"https://iea\.blob\.core\.windows\.net/assets/[^\"' >]+?OilMarketReport[^\"' >]*?\.pdf",
    re.IGNORECASE,
)


def resolve_pdf_url(landing_url: str) -> str | None:
    """Scrape the OMR landing page for the Azure-hosted PDF link."""
    r = requests.get(landing_url, headers=IEA_HEADERS, timeout=60)
    r.raise_for_status()
    html = r.text
    # Try a regex sweep first — it catches both <a href> and JSON-embedded refs.
    m = PDF_RX.search(html)
    if m:
        return m.group(0)
    # Fallback: parse anchors and look for OilMarketReport in href.
    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "iea.blob.core.windows.net/assets" in href and "OilMarketReport" in href and href.lower().endswith(".pdf"):
            return href
    return None


def fetch_pdf(url: str) -> bytes:
    r = requests.get(url, headers=IEA_HEADERS, timeout=180)
    r.raise_for_status()
    return r.content


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM inclusive, e.g. 2024-05")
    ap.add_argument("--end",   required=True, help="YYYY-MM inclusive, e.g. 2026-04")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    data = json.loads(LANDING_PATH.read_text())
    landings = data["landing_urls"]
    pdf_url_fallbacks = data.get("pdf_urls", {})

    for d in iter_months(args.start, args.end):
        label = month_label(d)
        if label not in landings:
            print(f"[skip] {label}: not in landing_urls", flush=True)
            continue
        dest = GT_SOURCE / f"{label}.pdf"
        if dest.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue

        pdf_url: str | None = None
        try:
            pdf_url = resolve_pdf_url(landings[label])
        except requests.RequestException as e:
            print(f"[warn] {label}: landing fetch failed ({e}); trying fallback", flush=True)

        if pdf_url is None and label in pdf_url_fallbacks:
            pdf_url = pdf_url_fallbacks[label]
            print(f"[fallback] {label}: using verified pdf_urls entry", flush=True)

        if pdf_url is None:
            print(f"[err]  {label}: no PDF URL resolvable", flush=True); continue

        try:
            content = fetch_pdf(pdf_url)
            if len(content) < 200_000:
                print(f"[err]  {label}: PDF too small ({len(content)} bytes); skipping", flush=True)
                continue
            dest.write_bytes(content)
            print(f"[ok]   {label}: {len(content):,} bytes  <-  {pdf_url.split('/')[-1]}", flush=True)
        except requests.HTTPError as e:
            print(f"[err]  {label}: {e}", flush=True)
        time.sleep(1.5)

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
