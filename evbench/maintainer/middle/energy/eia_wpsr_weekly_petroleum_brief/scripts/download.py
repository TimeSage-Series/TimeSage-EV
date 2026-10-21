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
from _common import TS_SOURCE, HEADERS, eia_api_key  # noqa: E402
from _common import GT_SOURCE, HEADERS, recent_wednesdays, iter_weeks, parse_label  # noqa: E402


# --- step: timeseries ----------------------------------------------------

EIA_BASE = "https://api.eia.gov/v2/petroleum"

# Five WPSR API series we need. Each is (route, params, friendly_name).
SERIES = [
    # Commercial crude oil ending stocks excl SPR (Table 1).
    ("stoc/wstk",  {"facets[process][]": "SAX", "facets[duoarea][]": "NUS"},
     "commercial_crude_stocks_excl_spr"),
    # Refiner net input — US national (Table 2).
    ("pnp/wiup",   {"facets[process][]": "YIR", "facets[duoarea][]": "NUS"},
     "refiner_net_input_us"),
    # Refinery operable capacity — US national (Table 2).
    ("pnp/wiup",   {"facets[process][]": "YRL", "facets[duoarea][]": "NUS"},
     "refinery_operable_capacity_us"),
    # Refinery utilization — US national. Series ID workaround per v0 known_issue.
    ("pnp/wiup",   {"facets[series][]": "WPULEUS3"},
     "refinery_utilization_us"),
    # Product supplied — gasoline (Tier 3 demand). EPM0F = Finished motor gasoline.
    ("cons/wpsup", {"facets[process][]": "VPP", "facets[product][]": "EPM0F",
                    "facets[duoarea][]": "NUS"},
     "gasoline_product_supplied"),
    # Product supplied — total crude+products (overall demand proxy).
    ("cons/wpsup", {"facets[process][]": "VPP", "facets[product][]": "EPOO",
                    "facets[duoarea][]": "NUS"},
     "total_product_supplied"),
]


def fetch(route: str, params: dict, start: str, end: str, api_key: str) -> dict:
    q = {
        "api_key": api_key, "frequency": "weekly", "data[0]": "value",
        "start": start, "end": end,
        "sort[0][column]": "period", "sort[0][direction]": "asc",
        "length": 5000,
        **params,
    }
    url = f"{EIA_BASE}/{route}/data/?{urllib.parse.urlencode(q, doseq=True)}"
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD inclusive (Wednesday)")
    ap.add_argument("--end",   required=True, help="YYYY-MM-DD inclusive (Wednesday)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    key = eia_api_key()
    if not key:
        print("[err] EIA_API_KEY not set (env or scenarios_v0/energy/.env)", flush=True); return

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    for route, params, name in SERIES:
        path = TS_SOURCE / f"wpsr_{name}_{args.start}_{args.end}.json"
        if path.exists() and not args.force:
            print(f"[skip] {name}", flush=True); continue
        try:
            data = fetch(route, params, args.start, args.end, key)
            path.write_text(json.dumps(data, indent=2))
            n = len(data.get("response", {}).get("data", []))
            print(f"[ok]  {name}: {n} rows", flush=True)
        except requests.HTTPError as e:
            print(f"[err] {name}: {e}", flush=True)
        time.sleep(1.5)  # EIA Akamai polite jitter


# --- step: gt ------------------------------------------------------------
ARCHIVE = "https://www.eia.gov/petroleum/supply/weekly/archive"


def _get(url: str, dest: Path, min_bytes: int = 5_000) -> str:
    r = requests.get(url, headers=HEADERS, timeout=60)
    if r.status_code != 200:
        return f"HTTP {r.status_code}"
    if len(r.content) < min_bytes:
        return f"too small ({len(r.content)} bytes)"
    dest.write_bytes(r.content)
    return "ok"


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (Wed)")
    ap.add_argument("--end",   required=True, help="YYYY-MM-DD (Wed)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    start = parse_label(args.start); end = parse_label(args.end)

    for wed in iter_weeks(start, end):
        ymd = wed.strftime("%Y_%m_%d")
        label = wed.isoformat()
        for kind, fname in (("highlights", f"{label}_highlights.pdf"),
                            ("wpsrall",    f"{label}_full.pdf")):
            url = f"{ARCHIVE}/{wed.year}/{ymd}/pdf/{kind}.pdf"
            dest = GT_SOURCE / fname
            if dest.exists() and not args.force:
                print(f"[skip] {fname}", flush=True); continue
            status = _get(url, dest)
            print(f"[{status:6s}] {fname}", flush=True)
            time.sleep(1.5)  # Akamai polite jitter

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
