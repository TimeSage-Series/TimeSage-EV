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
import csv
import sys
import urllib.request
sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    CDC_SOQL_URL,
    GT_SOURCE,
    NETWORKS,
    TS_SOURCE,
    join_weekly,
)


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> None:
    root = Path(__file__).resolve().parents[1]
    print(f"Source artifacts are checked in under {root / 'timeseries_source'}")


# --- step: gt ------------------------------------------------------------
def fetch():
    req = urllib.request.Request(
        CDC_SOQL_URL,
        headers={"User-Agent": "TimeSage-EV/1.0 (research)"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8")


def _step_gt() -> int:
    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    GT_SOURCE.mkdir(parents=True, exist_ok=True)

    raw_path = TS_SOURCE / "respnet_raw.csv"
    if not raw_path.exists():
        print(f"Downloading RESP-NET data from {CDC_SOQL_URL}")
        text = fetch()
        raw_path.write_text(text, encoding="utf-8")
    print(f"Raw rows file: {raw_path}")

    rows = list(csv.DictReader(raw_path.open()))
    print(f"Raw rows: {len(rows)}")

    joined = join_weekly(rows)

    # Per-network archive CSVs (extended history).
    for net in NETWORKS:
        out_path = GT_SOURCE / f"{net}.csv"
        with out_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["week_ending_date", "weekly_rate_per_100k"])
            for d, m in sorted(joined.items()):
                if net in m:
                    w.writerow([d, f"{m[net]:.3f}"])
        print(f"Wrote {out_path}")

    # Combined archive (sum of three) for weeks where all three are present.
    out_path = GT_SOURCE / "Combined.csv"
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["week_ending_date", "combined_rate_per_100k",
                    "covid_rate_per_100k", "flu_rate_per_100k",
                    "rsv_rate_per_100k"])
        for d, m in sorted(joined.items()):
            if all(k in m for k in NETWORKS):
                c = m["COVID-NET"]
                fl = m["FluSurv-NET"]
                r = m["RSV-NET"]
                w.writerow([
                    d,
                    f"{c + fl + r:.3f}",
                    f"{c:.3f}",
                    f"{fl:.3f}",
                    f"{r:.3f}",
                ])
    print(f"Wrote {out_path}")
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
