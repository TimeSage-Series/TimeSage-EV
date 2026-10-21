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
import datetime as dt
import sys
from pathlib import Path
from typing import Iterable
sys.path.insert(0, str(Path(__file__).parent))
from _common import (   # noqa: E402
    TS_SOURCE, INSTANCES, iter_months, month_label, release_date_for,
)
import json
from _common import GT_SOURCE, INSTANCES, iter_months, month_label  # noqa
from _html_parser import parse_mdo   # noqa


# --- step: timeseries ----------------------------------------------------


def _iso_week_label(d: dt.date) -> str:
    iy, iw, _ = d.isocalendar()
    return f"{iy:04d}-W{iw:02d}"


def _parse_usdm_csv(path: Path) -> list[dict]:
    """Parse the USDM CSV. The API serves columns:
    MapDate,None,D0,D1,D2,D3,D4,ValidStart,ValidEnd,StatisticFormatID
    `MapDate` is the Tuesday week_ending; `ValidEnd` is the same value
    a day off. We treat MapDate as authoritative.
    """
    rows: list[dict] = []
    with path.open() as f:
        reader = csv.DictReader(f)
        for raw in reader:
            mapdate = (raw.get("MapDate") or raw.get("ValidEnd") or "").strip()
            if not mapdate:
                continue
            d = _parse_date(mapdate)
            if d is None:
                continue
            rows.append({
                "week_ending": d,
                "iso_week":    _iso_week_label(d),
                "none_pct":    _to_float(raw.get("None")),
                "d0_pct":      _to_float(raw.get("D0")),
                "d1_pct":      _to_float(raw.get("D1")),
                "d2_pct":      _to_float(raw.get("D2")),
                "d3_pct":      _to_float(raw.get("D3")),
                "d4_pct":      _to_float(raw.get("D4")),
            })
    rows.sort(key=lambda r: r["week_ending"])
    return rows


def _parse_date(s: str) -> dt.date | None:
    s = s.strip()
    # USDM API returns several date formats: '2024-05-21', '5/21/2024',
    # '2024-05-21T00:00:00', '20240521' (YYYYMMDD compact form), etc.
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%-m/%-d/%Y"):
        try:
            return dt.datetime.strptime(s.split("T")[0] if "T" in s else s, fmt).date()
        except ValueError:
            continue
    # Best-effort fallback: try to parse iso prefix
    try:
        return dt.date.fromisoformat(s[:10])
    except Exception:
        return None


def _to_float(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _latest_csv() -> Path | None:
    candidates = sorted(TS_SOURCE.glob("conus_*.csv"))
    return candidates[-1] if candidates else None


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    csv_path = _latest_csv()
    if csv_path is None:
        print("[err] no USDM CONUS CSV in timeseries_source/; run "
              "`download.py timeseries` first.")
        return
    rows = _parse_usdm_csv(csv_path)
    if not rows:
        print(f"[err] {csv_path.name} had no parseable rows.")
        return

    for y, m in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        release = release_date_for(y, m)
        # Include every USDM week whose week_ending <= release date.
        # Also tag the most recent such week as the "snapshot the
        # forecaster saw" (is_issue_release_week=1).
        kept = [r for r in rows if r["week_ending"] <= release]
        if not kept:
            print(f"[skip] {label}: no USDM rows on or before {release}", flush=True)
            continue
        last_we = kept[-1]["week_ending"]

        out_dir = INSTANCES / label
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "timeseries.csv", "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow([
                "week_ending", "iso_week", "none_pct",
                "d0_pct", "d1_pct", "d2_pct", "d3_pct", "d4_pct",
                "is_issue_release_week",
            ])
            for r in kept:
                wr.writerow([
                    r["week_ending"].isoformat(),
                    r["iso_week"],
                    _fmt(r["none_pct"]),
                    _fmt(r["d0_pct"]),
                    _fmt(r["d1_pct"]),
                    _fmt(r["d2_pct"]),
                    _fmt(r["d3_pct"]),
                    _fmt(r["d4_pct"]),
                    1 if r["week_ending"] == last_we else 0,
                ])
        print(f"[ok]  {label}: {len(kept)} USDM weeks "
              f"({kept[0]['week_ending']} .. {last_we})", flush=True)


def _fmt(v: float | None) -> str:
    return "" if v is None else f"{v:.2f}"


# --- step: gt ------------------------------------------------------------
def synthesize_uncertainty(sentences: list[str]) -> str:
    """Compose a <=3-sentence uncertainty summary from the verbatim
    sentences extracted by the parser."""
    if not sentences:
        return ""
    # Take the first three, trim to 3 sentences total.
    return " ".join(sentences[:3])


def build_instance(label: str) -> tuple[dict | None, str | None]:
    src = GT_SOURCE / f"{label}.html"
    if not src.exists():
        return None, None
    parsed = parse_mdo(src)

    gt = {
        # Canonical categorical answer fields (per scenario.yaml).
        "regions_persists": parsed["regions_persists"],
        "regions_develops": parsed["regions_develops"],
        "regions_improves": parsed["regions_improves"],
        "regions_removes":  parsed["regions_removes"],
        "key_drivers":      parsed["key_drivers"],
        "uncertainties":    synthesize_uncertainty(parsed["uncertainty_sentences"]),

        # Verbatim sentence references for V4 / LLM-judge grounding.
        "supporting_evidence_reference": parsed["driver_sentences"][:6],
        "driver_sentences_reference":    parsed["driver_sentences"],
        "uncertainty_sentences_reference": parsed["uncertainty_sentences"],
        "narrative_excerpt":             parsed["narrative_excerpt"],
        "header":                        parsed["header"],
        "source_file":                   parsed["source_path"],
    }

    # Build gt_evidence.md
    md = [
        f"# Evidence — {label}",
        "",
        f"Source: `gt_source/{label}.html` (NOAA CPC Monthly Drought Outlook narrative)",
        "",
        f"- **Issued**: {gt['header'].get('issued')}",
        f"- **Valid**: {gt['header'].get('valid')}",
        "",
        "## Categorical regional outcomes (parsed from narrative)",
        "",
        f"- **regions_persists** = {gt['regions_persists']}",
        f"- **regions_develops** = {gt['regions_develops']}",
        f"- **regions_improves** = {gt['regions_improves']}",
        f"- **regions_removes**  = {gt['regions_removes']}",
        "",
        "## Key drivers (canonical keys detected)",
        "",
    ]
    for d in gt["key_drivers"]:
        md.append(f"- {d}")
    md += ["", "## Verbatim driver sentences (V4 traceability)", ""]
    for s in gt["driver_sentences_reference"]:
        md.append(f"- {s}")
    md += ["", "## Verbatim uncertainty sentences (V4 traceability)", ""]
    for s in gt["uncertainty_sentences_reference"]:
        md.append(f"- {s}")
    md += ["", "## Narrative excerpt (first 3000 chars)", "", "```", gt["narrative_excerpt"], "```"]
    return gt, "\n".join(md)


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    for y, m in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}: instance dir missing", flush=True); continue
        gt, ev = build_instance(label)
        if gt is None:
            print(f"[skip] {label}: no gt_source HTML", flush=True); continue
        (out / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        (out / "gt_evidence.md").write_text(ev)
        n_p = len(gt["regions_persists"]); n_d = len(gt["regions_develops"])
        n_i = len(gt["regions_improves"]); n_r = len(gt["regions_removes"])
        print(f"[ok]  {label}: persists={n_p} develops={n_d} improves={n_i} removes={n_r}",
              flush=True)

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
