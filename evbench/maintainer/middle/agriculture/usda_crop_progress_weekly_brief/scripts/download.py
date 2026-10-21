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
import time
import urllib.parse
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, HEADERS, nass_api_key  # noqa: E402
import re
import urllib.request
from _common import GT_SOURCE, HEADERS, usda_week_label  # noqa: E402


# --- step: timeseries ----------------------------------------------------

NASS = "https://quickstats.nass.usda.gov/api/api_GET/"

QUERIES = {
    "corn_planted_pct":           {"commodity_desc": "CORN", "statisticcat_desc": "PROGRESS",
                                   "short_desc": "CORN - PROGRESS, MEASURED IN PCT PLANTED"},
    "corn_emerged_pct":           {"commodity_desc": "CORN", "statisticcat_desc": "PROGRESS",
                                   "short_desc": "CORN - PROGRESS, MEASURED IN PCT EMERGED"},
    "corn_harvested_pct":         {"commodity_desc": "CORN", "statisticcat_desc": "PROGRESS",
                                   "short_desc": "CORN, GRAIN - PROGRESS, MEASURED IN PCT HARVESTED"},
    "corn_condition_good_pct":    {"commodity_desc": "CORN", "statisticcat_desc": "CONDITION",
                                   "short_desc": "CORN - CONDITION, MEASURED IN PCT GOOD"},
    "soybeans_planted_pct":       {"commodity_desc": "SOYBEANS", "statisticcat_desc": "PROGRESS",
                                   "short_desc": "SOYBEANS - PROGRESS, MEASURED IN PCT PLANTED"},
    "soybeans_harvested_pct":     {"commodity_desc": "SOYBEANS", "statisticcat_desc": "PROGRESS",
                                   "short_desc": "SOYBEANS - PROGRESS, MEASURED IN PCT HARVESTED"},
    "soybeans_condition_good_pct": {"commodity_desc": "SOYBEANS", "statisticcat_desc": "CONDITION",
                                    "short_desc": "SOYBEANS - CONDITION, MEASURED IN PCT GOOD"},
    "wheat_winter_condition_good_pct": {"commodity_desc": "WHEAT", "statisticcat_desc": "CONDITION",
                                        "short_desc": "WHEAT, WINTER - CONDITION, MEASURED IN PCT GOOD"},
}


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years-from", type=int, required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    key = nass_api_key()
    if not key:
        print("[err] NASS_API_KEY not set", flush=True); return

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    for name, base_params in QUERIES.items():
        path = TS_SOURCE / f"{name}.json"
        if path.exists() and not args.force:
            print(f"[skip] {name}", flush=True); continue
        params = {
            "key": key, "format": "JSON",
            "agg_level_desc": "NATIONAL",
            "year__GE": str(args.years_from),
            **base_params,
        }
        url = f"{NASS}?{urllib.parse.urlencode(params, doseq=True)}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            data = r.json()
            path.write_text(json.dumps(data, indent=2))
            n = len(data.get("data", []))
            print(f"[ok]  {name}: {n} rows", flush=True)
        except (requests.HTTPError, json.JSONDecodeError) as e:
            print(f"[err] {name}: {e}", flush=True)
        time.sleep(1.0)


# --- step: gt ------------------------------------------------------------
ESMIS_BASE = "https://esmis.nal.usda.gov"
ARCHIVE_ID = "8336h188j"


def scrape_pdf_urls(max_pages: int = 25) -> dict[tuple[int, int], str]:
    """Return {(year, week): url} discovered from the ESMIS archive."""
    out: dict[tuple[int, int], str] = {}
    seen = set()
    for page in range(1, max_pages + 1):
        url = f"{ESMIS_BASE}/concern/publications/{ARCHIVE_ID}?page={page}&per_page=100"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"page {page}: error {e}", flush=True); break
        page_pdfs = re.findall(
            r'href="(/sites/default/release-files/[^"]+prog\d{4}(?:_\d+)?\.pdf)"',
            html, re.IGNORECASE,
        )
        new = [p for p in page_pdfs if p not in seen]
        if not new: break
        seen.update(new)
        for p in new:
            m = re.search(r"prog(\d{2})(\d{2})(?:_\d+)?\.pdf$", p)
            if not m: continue
            ww = int(m.group(1)); yy = 2000 + int(m.group(2))
            # Prefer the FIRST occurrence (most recent first ordering on ESMIS).
            out.setdefault((yy, ww), ESMIS_BASE + p)
        time.sleep(0.4)
    return out


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-week", required=True, help="YYYY-wkWW inclusive")
    ap.add_argument("--end-week",   required=True, help="YYYY-wkWW inclusive")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    print("Scraping ESMIS archive for PDF URLs...", flush=True)
    by_key = scrape_pdf_urls()
    print(f"Found {len(by_key)} PDFs in archive.", flush=True)

    sy, sw = (int(x) for x in args.start_week.replace("wk", "").split("-"))
    ey, ew = (int(x) for x in args.end_week.replace("wk", "").split("-"))

    for (yy, ww), url in sorted(by_key.items()):
        # Filter by inclusive window.
        if (yy, ww) < (sy, sw) or (yy, ww) > (ey, ew):
            continue
        label = usda_week_label(yy, ww)
        dest = GT_SOURCE / f"{label}.pdf"
        if dest.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            if r.status_code == 200 and len(r.content) > 20_000:
                dest.write_bytes(r.content)
                print(f"[ok]   {label}", flush=True)
            else:
                print(f"[fail] {label}: HTTP {r.status_code} ({len(r.content)} bytes)", flush=True)
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
