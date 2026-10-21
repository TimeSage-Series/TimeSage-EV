#!/usr/bin/env python3
"""Build instances for this scenario's this scenario.

    python scripts/format.py                 # every step, in order: timeseries -> gt
    python scripts/format.py timeseries    # one step
    python scripts/format.py gt [flags]    # …with that step's own flags
    python scripts/format.py all [flags]     # every step, flags forwarded to each
    python scripts/format.py --list          # list the steps

Merged from format_timeseries.py and format_gt.py. Each step keeps the argument
parser it had before, so every flag that used to work still works — pass it
after the step name.
"""
from __future__ import annotations
import csv
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import ALL_SERIES, TS_SOURCE


# --- step: timeseries ----------------------------------------------------


def read_series(sid: str) -> dict[str, float]:
    src = TS_SOURCE / f"{sid}.csv"
    out: dict[str, float] = {}
    with src.open() as f:
        for row in csv.DictReader(f):
            d = (row.get("observation_date") or "").strip()
            v = (row.get(sid) or "").strip()
            if not d or not v:
                continue
            try:
                out[d[:7]] = float(v)
            except ValueError:
                pass
    return out


def shift_month(period: str, months: int) -> str:
    y, m = period.split("-")
    yi = int(y); mi = int(m)
    mi += months
    while mi <= 0:
        yi -= 1; mi += 12
    while mi > 12:
        yi += 1; mi -= 12
    return f"{yi:04d}-{mi:02d}"


def yoy_pct(cur: float | None, year_ago: float | None) -> float | None:
    if cur is None or year_ago is None or year_ago == 0:
        return None
    return (cur - year_ago) / year_ago * 100.0


def _fmt(x, n: int) -> str:
    if x is None:
        return ""
    s = f"{x:.{n}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _step_timeseries() -> int:
    levels: dict[str, dict[str, float]] = {}
    for short, sid in ALL_SERIES:
        levels[short] = read_series(sid)

    # Build YoY per series
    yoys: dict[str, dict[str, float]] = {}
    for short, _ in ALL_SERIES:
        d: dict[str, float] = {}
        src = levels[short]
        for p, v in src.items():
            ya = shift_month(p, -12)
            y = yoy_pct(v, src.get(ya))
            if y is not None:
                d[p] = round(y, 4)
        yoys[short] = d

    # MoM YoY-pp delta per series. Walk back as far as needed to find the
    # most recent prior YoY, so that the BLS 2025-10 shutdown gap doesn't
    # leave 2025-11 with a null delta (we treat 2025-11 as the next month
    # of available data after 2025-09 for delta purposes).
    deltas: dict[str, dict[str, float]] = {}
    for short, _ in ALL_SERIES:
        d: dict[str, float] = {}
        src = yoys[short]
        for p, v in src.items():
            prev_p = shift_month(p, -1)
            for back in range(1, 6):
                cand = shift_month(p, -back)
                if cand in src:
                    prev_p = cand
                    break
            if prev_p in src:
                d[p] = round(v - src[prev_p], 4)
        deltas[short] = d

    # Union of periods that have a YoY value across all 5 series
    headline_short = ALL_SERIES[0][0]
    all_periods = sorted(yoys[headline_short].keys())

    out = TS_SOURCE / "medical_care_cpi_full.csv"
    cols = ["period"]
    for short, _ in ALL_SERIES:
        cols.append(f"{short}_index")
        cols.append(f"{short}_yoy_pct")
        cols.append(f"{short}_mom_yoy_delta_pp")

    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in all_periods:
            row = [p]
            for short, _ in ALL_SERIES:
                row.append(_fmt(levels[short].get(p), 4))
                row.append(_fmt(yoys[short].get(p), 3))
                row.append(_fmt(deltas[short].get(p), 3))
            w.writerow(row)

    print(f"wrote {out} with {len(all_periods)} rows")
    return 0


# --- step: gt ------------------------------------------------------------
def _step_gt() -> None:
    root = Path(__file__).resolve().parents[1]
    print(f"Ground truth artifacts are checked in under {root / 'instances'}")

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
