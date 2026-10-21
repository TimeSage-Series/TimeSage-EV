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
import argparse
import csv
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    TS_SOURCE, INSTANCES, parse_oni_ascii, iter_months,
    SEASON_CENTERED_MONTH, season_centered_date,
)
import json
from _common import GT_SOURCE, INSTANCES, iter_months, month_long  # noqa: E402
from _html_parser import parse_issue  # noqa: E402


# --- step: timeseries ----------------------------------------------------


CSV_COLUMNS = [
    "season", "year", "season_label", "centered_month",
    "nino34_total_c", "nino34_anomaly_c",
]


def latest_oni_text() -> str:
    files = sorted(TS_SOURCE.glob("oni-*.ascii.txt"))
    if not files:
        raise SystemExit("[error] no ONI snapshot — run `download.py timeseries`")
    return files[-1].read_text(encoding="utf-8")


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    rows = parse_oni_ascii(latest_oni_text())
    if not rows:
        raise SystemExit("[error] ONI parse 0 rows")
    for r in rows:
        r["_date"] = season_centered_date(r["season"], r["year"])
    rows.sort(key=lambda r: r["_date"])

    n = 0
    for period in iter_months(args.instance_start, args.instance_end):
        y, m = (int(x) for x in period.split("-"))
        import datetime as dt
        cutoff = dt.date(y, m, 28)   # cover the issue release within month
        visible = [r for r in rows if r["_date"] <= cutoff]
        folder = INSTANCES / period
        folder.mkdir(parents=True, exist_ok=True)
        out_csv = folder / "timeseries.csv"
        with out_csv.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(CSV_COLUMNS)
            for r in visible:
                w.writerow([
                    r["season"], r["year"],
                    f"{r['year']:04d}-{r['season']}",
                    SEASON_CENTERED_MONTH[r["season"]],
                    f"{r['total_sst_c']:.2f}",
                    f"{r['anomaly_c']:.2f}",
                ])
        n += 1
        latest = visible[-1]
        print(f"[ok]  {period}: {len(visible)} ONI seasons; latest "
              f"{latest['season']} {latest['year']} anom={latest['anomaly_c']:+.2f}")
    print(f"[done] wrote {n} timeseries.csv files")
    return 0


# --- step: gt ------------------------------------------------------------
def build(period: str) -> tuple[dict, str] | tuple[None, None]:
    path = GT_SOURCE / f"{period}.html"
    if not path.exists():
        return None, None
    parsed = parse_issue(path)
    gt = {
        "issue_date":           parsed["issue_date"],
        "synopsis_summary":     parsed["synopsis_summary"],
        "plume_outlook":        parsed["plume_outlook"],
        "iod_forecast":         parsed["iod_forecast"],
        "key_drivers":          parsed["key_drivers"],
        "cpc_iri_comparison":   parsed["cpc_iri_comparison"],
        "risks_uncertainties":  parsed["risks_uncertainties"],
        "synopsis_reference_verbatim": parsed["synopsis_summary"],
        "key_drivers_reference_sentences": parsed["key_drivers"],
        "risks_reference_text": parsed["risks_uncertainties"],
        "full_text_reference":  parsed["full_text"][:6000],
    }
    long_name = month_long(period)
    ev = (
        f"# Evidence — IRI ENSO QuickLook ({long_name})\n\n"
        f"Source artifact: `gt_source/{period}.html`\n"
        f"Public URL pattern: `/our-expertise/climate/forecasts/enso/"
        f"<YYYY>-<month_long>-quick-look/`\n\n"
        f"## Per-answer-field citations\n\n"
        f"- **issue_date** → `{gt['issue_date']}` — extracted from "
        f"\"ENSO Update [<date>]\" header.\n"
        f"- **synopsis_summary** → first lead-sentence describing ENSO state.\n"
        f"- **plume_outlook** → phase=`{gt['plume_outlook']['phase']}`, "
        f"probability_pct=`{gt['plume_outlook']['probability_pct']}` "
        f"(from the CCSR/IRI plume forecast).\n"
        f"- **iod_forecast** → IOD direction sentence (Indian Ocean Dipole; "
        f"a separate climate mode IRI tracks alongside ENSO).\n"
        f"- **key_drivers** → {len(gt['key_drivers'])} sentences matched "
        f"by the IRI driver-vocabulary anchors (CCSR/IRI plume, IOD, "
        f"subsurface, model spread/bias).\n"
        f"- **cpc_iri_comparison** → sentence(s) describing where IRI's "
        f"objective forecast agrees / disagrees with the official CPC forecast.\n"
        f"- **risks_uncertainties** → sentences flagging spring barrier, "
        f"model bias, low confidence.\n"
        f"- **supporting_evidence** → at least 3 observations citing CSV "
        f"rows or past IRI QuickLook issues.\n\n"
        f"## Traceability\n\n"
        f"- IRI ENSO QuickLook is the IRI/Columbia objective companion to the "
        f"NOAA CPC ENSO Diagnostic Discussion. Both are issued the same week "
        f"each month; CPC uses human-adjusted forecasts while IRI surfaces "
        f"the raw CCSR/IRI plume model. The two scenarios cover the same "
        f"climate state from complementary forecasting angles.\n"
    )
    return gt, ev


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    n_ok = n_skip = 0
    for period in iter_months(args.instance_start, args.instance_end):
        folder = INSTANCES / period
        gt, ev = build(period)
        if gt is None:
            print(f"[skip] {period}: shtml missing")
            n_skip += 1; continue
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "ground_truth.json").write_text(json.dumps(gt, indent=2,
                                                              ensure_ascii=False))
        (folder / "gt_evidence.md").write_text(ev, encoding="utf-8")
        n_ok += 1
        print(f"[ok]  {period}: plume={gt['plume_outlook']['phase']!r} "
              f"{gt['plume_outlook']['probability_pct']}% "
              f"IOD={'yes' if gt.get('iod_forecast') else 'none'} "
              f"drivers={len(gt['key_drivers'])}")
    print(f"[done] ok={n_ok}  skip={n_skip}")
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
