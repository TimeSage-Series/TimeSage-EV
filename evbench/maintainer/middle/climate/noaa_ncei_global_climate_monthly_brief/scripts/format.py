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
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    GT_SOURCE, TS_SOURCE, INSTANCES,
    iter_periods, period_to_yyyymm, yyyymm_to_period,
)
from _html_parser import parse_brief  # noqa: E402
from _common import (  # noqa: E402
    GT_SOURCE, INSTANCES,
    iter_periods, period_to_yyyymm, month_name_long,
    NCEI_URL_PATTERN, CAAG_GLOBAL_TS,
)
MAINTAINER_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(MAINTAINER_ROOT / "lib"))
from narrative_extract import build_narrative_md_block, load_source_text  # noqa: E402


# --- step: timeseries ----------------------------------------------------

COLUMNS = [
    "period",                          # YYYY-MM
    "global_anomaly_c",
    "global_rank_warmest",
    "total_years_compared",
    "arctic_sea_ice_rank",
    "antarctic_sea_ice_rank",
    "leading_regional_callouts_csv",   # comma-joined; for the agent to restate
    "sea_ice_status_sentence",         # one-line summary of Arctic+Antarctic
]

HTML_RX = re.compile(r"global-climate-(\d{6})\.html$")


def parse_or_cache(period: str) -> dict | None:
    """Return parsed fields for `period`, caching the per-period dict to
    `timeseries_source/<YYYYMM>.json` to avoid re-parsing on every run.
    """
    yyyymm = period_to_yyyymm(period)
    cache = TS_SOURCE / f"{yyyymm}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    html_path = GT_SOURCE / f"global-climate-{yyyymm}.html"
    if not html_path.exists():
        return None
    parsed = parse_brief(html_path)
    # Drop the bulky text fields before caching.
    slim = {k: v for k, v in parsed.items()
            if k not in ("headline_paragraph", "full_text")}
    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(slim, indent=2, default=str))
    return slim


def gt_periods_present() -> list[str]:
    out: list[str] = []
    for p in sorted(GT_SOURCE.glob("global-climate-*.html")):
        m = HTML_RX.search(p.name)
        if not m:
            continue
        out.append(yyyymm_to_period(m.group(1)))
    return out


def row_for(period: str, parsed: dict) -> list:
    callouts = parsed.get("leading_regional_callouts") or []
    return [
        period,
        parsed.get("global_anomaly_c"),
        parsed.get("global_rank_warmest"),
        parsed.get("total_years_compared"),
        parsed.get("arctic_sea_ice_rank"),
        parsed.get("antarctic_sea_ice_rank"),
        ",".join(callouts),
        parsed.get("sea_ice_status") or "",
    ]


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    ap.add_argument("--earliest-raw", default="2020-01",
                    help="Earliest cumulative period to include (default 2020-01).")
    args = ap.parse_args()

    all_present = gt_periods_present()
    if not all_present:
        print("[fatal] no NCEI HTML files in gt_source/; "
              "run `download.py timeseries` first.", file=sys.stderr)
        return 2

    # Parse every present period once.
    parsed_by_period: dict[str, dict] = {}
    for p in all_present:
        parsed = parse_or_cache(p)
        if parsed is not None:
            parsed_by_period[p] = parsed

    # Build CSVs.
    written = 0
    for inst in iter_periods(args.instance_start, args.instance_end):
        # Cumulative window: includes the query month itself (its row
        # is the latest row; the agent reads it to compose the digest).
        # The V7 guarantee at the per-instance level is enforced by
        # build_visible_reports.py — that manifest EXCLUDES the query-
        # month HTML so the agent never sees the verbatim narrative
        # NCEI wrote (which the LLM judge scores against).
        cumulative = [
            (p, parsed_by_period[p]) for p in sorted(parsed_by_period.keys())
            if args.earliest_raw <= p <= inst
        ]
        if not cumulative:
            print(f"[warn] {inst}: no past brief HTML available; "
                  f"timeseries.csv will be empty", flush=True)
        out_dir = INSTANCES / inst
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "timeseries.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(COLUMNS)
            for p, parsed in cumulative:
                w.writerow(row_for(p, parsed))
        print(f"[ok]  {inst}: {len(cumulative)} cumulative past rows", flush=True)
        written += 1

    print(f"\n[done] wrote {written} timeseries.csv files", flush=True)
    return 0


# --- step: gt ------------------------------------------------------------
def build(period: str) -> tuple[dict, str] | tuple[None, None]:
    yyyymm = period_to_yyyymm(period)
    html_path = GT_SOURCE / f"global-climate-{yyyymm}.html"
    if not html_path.exists():
        return None, None

    parsed = parse_brief(html_path)
    headline = parsed.get("headline_paragraph") or ""
    long_name = month_name_long(period)

    gt = {
        "global_anomaly_c":          parsed.get("global_anomaly_c"),
        "global_rank":               parsed.get("global_rank_warmest"),
        "is_warmest_on_record":      (parsed.get("global_rank_warmest") == 1),
        "leading_regional_callouts": parsed.get("leading_regional_callouts") or [],
        "report":             headline,
        "as_of_period":              period,
    }

    md_lines = [
        f"# Evidence — NOAA NCEI Assessing the Global Climate in {long_name}\n",
        f"Source artifact: `gt_source/global-climate-{yyyymm}.html`",
        f"Public URL: {NCEI_URL_PATTERN.format(period=yyyymm)}\n",
        "## Per-answer-field citations\n",
        f"- **global_anomaly_c** → `{gt['global_anomaly_c']}` °C — "
        f"extracted from the headline paragraph of the NCEI brief; "
        f"cross-traceable to the corresponding monthly row on "
        f"NOAA Climate at a Glance ({CAAG_GLOBAL_TS}).",
        f"- **global_rank** → `{gt['global_rank']}` "
        f"(out of `{gt['total_years_compared']}` years in the historical "
        f"record at NCEI publication time).",
        f"- **leading_regional_callouts** → `{gt['leading_regional_callouts']}`"
        f" — regions that NCEI explicitly calls out with a rank or anomaly "
        f"phrase in this month's brief.",
        f"- **sea_ice_status** → `{gt['sea_ice_status']}` — first sentence "
        f"in the brief that mentions Arctic / Antarctic sea ice.",
        "- **report** → graded by LLM judge against the verbatim "
        "NCEI headline paragraph reproduced below.",
        "- **supporting_evidence** → at least 3 observations, each citing "
        "either (a) a row/cell in `/root/timeseries.csv` (past months, "
        "STRICTLY before the query month) or (b) a section header in the "
        "NCEI brief (e.g. 'Monthly Temperature', 'Sea Ice').",
        "\n## Verbatim NCEI headline paragraph (for LLM judge)\n",
        headline or "*(headline paragraph could not be parsed)*",
        "\n## Sub-fields and cross-checks\n",
        f"- Arctic sea-ice rank (1 = lowest on record): "
        f"`{gt['arctic_sea_ice_rank']}`",
        f"- Antarctic sea-ice rank (1 = lowest on record): "
        f"`{gt['antarctic_sea_ice_rank']}`",
        "- Ocean / land / hemispheric anomalies: not reported numerically "
        "in the modern NCEI brief format; cross-check against the brief's "
        "rank phrases when relevant.",
        "\n## Traceability notes (V4)\n",
        "- The NCEI 'Assessing the Global Climate in <Month> <Year>' news "
        "article is the canonical Middle-tier brief. All headline numbers "
        "map to the same month's row of Climate at a Glance global "
        "time-series tables (linked above).",
        "agent should cite the cell coordinate in `/root/timeseries.csv` "
        "using the row's `period` column and the relevant numeric column.",
    ]
    ev = "\n".join(md_lines)
    # Append narrative-extract block.
    src_text, src_pages = load_source_text(html_path)
    if src_text:
        ev = ev.rstrip() + "\n\n" + build_narrative_md_block(
            f"gt_source/{html_path.name}", src_text, pages=src_pages,
        )
    return gt, ev


def _step_gt() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    n_ok, n_skip = 0, 0
    for inst in iter_periods(args.instance_start, args.instance_end):
        out_dir = INSTANCES / inst
        gt, ev = build(inst)
        if gt is None:
            print(f"[skip] {inst}: gt_source HTML missing", flush=True)
            n_skip += 1
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2,
                                                              default=str))
        (out_dir / "gt_evidence.md").write_text(ev)
        n_ok += 1
        print(f"[ok]  {inst}: rank={gt['global_rank']} "
              f"anomaly={gt['global_anomaly_c']}°C "
              f"callouts={len(gt['leading_regional_callouts'])}",
              flush=True)
    print(f"\n[done] ok={n_ok}  skip={n_skip}", flush=True)
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
