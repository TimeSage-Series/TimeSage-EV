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
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
import requests
sys.path.insert(0, str(Path(__file__).parent))
from _common import (TS_SOURCE, TSA_BASE_URL, classify,
                     week_label, sunday_of_iso_week, iter_weeks)  # noqa
import shutil
from _common import TS_SOURCE, GT_SOURCE, week_label, iter_weeks  # noqa

def _safe_copy(src, dst, _c=shutil.copy2):
    """Copy unless src and dst are the same file.

    gt_source/ and timeseries_source/ used to be separate directories, so a
    scenario could legitimately copy an artifact from one into the other. They
    are now one source/ tree, which turns those copies into copy-onto-self and
    raises SameFileError — bts_airline_load_factor_monthly failed exactly this
    way on loadfactor.csv.
    """
    from pathlib import Path as _P
    s, d = _P(src), _P(dst)
    try:
        if s.resolve() == d.resolve():
            return d
    except OSError:
        pass
    d.parent.mkdir(parents=True, exist_ok=True)
    return _c(str(s), str(d))



# --- step: timeseries ----------------------------------------------------


CELL_RE = re.compile(
    r'<td class="text-align-center">([^<]*)</td>',
    re.IGNORECASE,
)


def fetch_year_html(year: int) -> str:
    """Current year is served at the base URL; older years at /YYYY."""
    cur_year = dt.date.today().year
    if year == cur_year:
        url = TSA_BASE_URL
    else:
        url = f"{TSA_BASE_URL}/{year}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.text


def parse_daily_counts(html: str, year_hint: int) -> dict[dt.date, int]:
    """Parse <td class="text-align-center">DATE</td><td>COUNT</td> pairs."""
    cells = CELL_RE.findall(html)
    out: dict[dt.date, int] = {}
    # The page renders [date, count, date, count, ...] in document order.
    for i in range(0, len(cells) - 1, 2):
        date_s = cells[i].strip()
        count_s = cells[i + 1].strip()
        # date format "M/D/YYYY"
        try:
            m, day, y = date_s.split("/")
            d = dt.date(int(y), int(m), int(day))
        except (ValueError, IndexError):
            continue
        try:
            n = int(count_s.replace(",", "").replace(" ", ""))
        except ValueError:
            continue
        if d.year != year_hint:
            # ignore mis-tagged rows
            continue
        out[d] = n
    return out


def aggregate_iso_weeks(daily: dict[dt.date, int]) -> dict[tuple[int, int], int]:
    """Sum daily counts into (iso_year, iso_week) buckets.

    Returns a week's aggregate only if at least 6 of the 7 days are
    available. When exactly 6 days are present (typically at the
    earliest-year boundary where 2019-W01 is missing 2018-12-31 because
    TSA archives only go back to 2019), the result is scaled up by 7/6
    so the comparison stays on a like-for-like full-week basis. This
    scaling concerns only the 2019 baseline at most one week per year.
    """
    buckets: dict[tuple[int, int], list[tuple[dt.date, int]]] = defaultdict(list)
    for d, n in daily.items():
        iso = d.isocalendar()
        buckets[(iso.year, iso.week)].append((d, n))
    out: dict[tuple[int, int], int] = {}
    for k, items in buckets.items():
        s = sum(n for _, n in items)
        if len(items) >= 7:
            out[k] = s
        elif len(items) == 6:
            out[k] = int(round(s * 7 / 6))
    return out


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)

    weeks = list(iter_weeks(args.start, args.end))
    if not weeks:
        print("[err]  empty week range", flush=True); return

    if not args.force and all((TS_SOURCE / f"{week_label(s)}.json").exists()
                              for _, _, s in weeks):
        for _, _, s in weeks:
            print(f"[skip] {week_label(s)}", flush=True)
        return

    # Determine which calendar years we need: all instance years + 2019.
    # 2018 is included because ISO-W01 of 2019 starts on Mon 2018-12-31 and
    # we need that day to complete the 2019-W01 baseline.
    needed_years = {2018, 2019}
    for y, _, _ in weeks:
        needed_years.add(y)
        # ISO weeks at the boundary may cross calendar years; pull
        # neighbours just in case.
        needed_years.add(y - 1)
        needed_years.add(y + 1)
    # Drop future years.
    today = dt.date.today()
    needed_years = {y for y in needed_years if y <= today.year}

    daily: dict[dt.date, int] = {}
    for yr in sorted(needed_years):
        print(f"[fetch] TSA archive year={yr}", flush=True)
        try:
            html = fetch_year_html(yr)
        except requests.HTTPError as exc:
            print(f"[warn] fetch failed for year {yr}: {exc}", flush=True)
            continue
        cnt = parse_daily_counts(html, yr)
        print(f"[fetch] year {yr}: parsed {len(cnt)} daily rows", flush=True)
        daily.update(cnt)

    # Aggregate to ISO weeks.
    weekly = aggregate_iso_weeks(daily)
    print(f"[agg]  complete ISO-week aggregates: {len(weekly)}", flush=True)

    # Same-week baseline lookup: same (iso_week-of-year) but iso_year=2019.
    def baseline_2019(week: int) -> int | None:
        return weekly.get((2019, week))

    for y, w, sunday in weeks:
        label = week_label(sunday)
        path = TS_SOURCE / f"{label}.json"
        if path.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue
        throughput = weekly.get((y, w))
        baseline = baseline_2019(w)
        if throughput is None or baseline is None or baseline == 0:
            print(f"[empty] {label}: throughput={throughput} baseline={baseline}",
                  flush=True); continue
        recovery = round(throughput / baseline, 4)
        cat = classify(recovery)
        # Collect the 7 daily rows for the raw_row archive.
        days = []
        for offset in range(-6, 1):
            dd = sunday + dt.timedelta(days=offset)
            if dd in daily:
                days.append({"date": dd.isoformat(), "count": daily[dd]})
        payload = {
            "iso_week":      label,
            "week_ending":   sunday.isoformat(),
            "throughput":    throughput,
            "baseline_2019": baseline,
            "recovery_pct":  recovery,
            "recovery_band": cat,
            "raw_row":       {"days": days, "iso_week_of_year": w},
        }
        path.write_text(json.dumps(payload, indent=2))
        print(f"[ok]   {label}: throughput={throughput:,} baseline={baseline:,} "
              f"recovery_pct={recovery:.4f} -> {cat}", flush=True)


# --- step: gt ------------------------------------------------------------
def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    GT_SOURCE.mkdir(parents=True, exist_ok=True)
    for y, w, sunday in iter_weeks(args.start, args.end):
        label = week_label(sunday)
        src = TS_SOURCE / f"{label}.json"
        dst = GT_SOURCE / f"{label}.json"
        if not src.exists():
            print(f"[skip] {label}: timeseries_source missing", flush=True); continue
        if dst.exists() and not args.force:
            print(f"[skip] {label}", flush=True); continue
        _safe_copy(src, dst)
        print(f"[ok]   {label}", flush=True)

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
