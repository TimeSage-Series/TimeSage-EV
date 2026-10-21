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
from _shtml_parser import parse_issue  # noqa: E402


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
    path = GT_SOURCE / f"{period}.shtml"
    if not path.exists():
        return None, None
    parsed = parse_issue(path)
    gt = {
        # Required answer fields (deterministic anchors):
        "enso_alert_status":    parsed["alert_status"],
        "outlook_3mo":          parsed["outlook_3mo"],
        # Required answer fields (free-text; judge against references):
        "synopsis_summary":     parsed["synopsis_summary"],
        "key_drivers":          parsed["key_drivers"],
        "risks_uncertainties":  parsed["risks_uncertainties"],
        # Verbatim references for the LLM judge:
        "synopsis_reference_verbatim": parsed["synopsis_summary"],
        "key_drivers_reference_sentences": parsed["key_drivers"],
        "risks_reference_text": parsed["risks_uncertainties"],
        "full_text_reference":  parsed["full_text"][:8000],
    }
    long_name = month_long(period)
    ev = (
        f"# Evidence — CPC ENSO Diagnostic Discussion ({long_name})\n\n"
        f"Source artifact: `gt_source/{period}.shtml`\n"
        f"Public URL: see scripts/landing_urls.json (URL pattern "
        f"`enso_disc_<mmm><YYYY>/ensodisc.shtml`).\n\n"
        f"## Per-answer-field citations\n\n"
        f"- **enso_alert_status** → `{gt['enso_alert_status']}` — extracted "
        f"verbatim from the `ENSO Alert System Status:` line at the top of "
        f"the shtml.\n"
        f"- **synopsis_summary** → first 1-2 sentences after `Synopsis:` "
        f"in the shtml (verbatim, also stored in `synopsis_reference_verbatim`).\n"
        f"- **key_drivers** → {len(gt['key_drivers'])} sentences matched "
        f"by the driver-vocabulary anchors (SST anomalies, subsurface, "
        f"low-level winds, MJO, NMME / model guidance, …) in the body of "
        f"the shtml. See `_shtml_parser.DRIVER_TRIGGERS` for the closed list.\n"
        f"- **outlook_3mo** → first `(NN% chance of <Phase>)` match in the "
        f"body, with fallback to the `favors NMME guidance, predicting "
        f"<Phase>` phrase. Values: phase=`{gt['outlook_3mo']['phase']}`, "
        f"probability_pct=`{gt['outlook_3mo']['probability_pct']}`.\n"
        f"- **risks_uncertainties** → sentences matching the risk-anchor "
        f"set (uncertainty, spring barrier, model spread, low confidence, "
        f"less likely). The verbatim reference text is in "
        f"`risks_reference_text`.\n"
        f"- **supporting_evidence** → at least 3 observations; each must "
        f"cite either (a) a CSV row in `/root/timeseries.csv` or (b) a "
        f"section of a past ENSO DD listed in `/root/visible_reports.json`.\n\n"
        f"## Traceability\n\n"
        f"- The CPC ENSO DD is published on the 2nd Thursday of each month "
        f"jointly with IRI. Each issue is the official operational ENSO "
        f"diagnostic of record.\n"
        f"- ONI back-up: monthly Niño 3.4 anomaly time series at "
        f"https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt — the "
        f"cumulative seasons through the issue's data month are surfaced "
        f"in `/root/timeseries.csv`.\n"
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
        print(f"[ok]  {period}: alert={gt['enso_alert_status']!r:32s} "
              f"outlook={gt['outlook_3mo']['phase']!r} "
              f"{gt['outlook_3mo']['probability_pct']}% "
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
