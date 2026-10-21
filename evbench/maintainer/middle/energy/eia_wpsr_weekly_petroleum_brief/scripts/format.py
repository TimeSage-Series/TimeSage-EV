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
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, INSTANCES, iter_weeks, parse_label  # noqa: E402
from _common import GT_SOURCE, INSTANCES, parse_label  # noqa: E402
MAINTAINER_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(MAINTAINER_ROOT / "lib"))
from narrative_extract import build_narrative_md_block, load_source_text  # noqa: E402


# --- step: timeseries ----------------------------------------------------

# (filename glob, series filter, output column)
# series filter is checked against the 'series' field; None means take any
# (only valid when there's a single series in the file).
PIPE = [
    ("wpsr_commercial_crude_stocks_excl_spr_*.json", "WCESTUS1", "commercial_crude_kbbl"),
    ("wpsr_refiner_net_input_us_*.json",             None,        "refiner_input_kbd"),
    ("wpsr_refinery_operable_capacity_us_*.json",    None,        "refinery_capacity_kbd"),
    ("wpsr_refinery_utilization_us_*.json",          "WPULEUS3",  "refinery_util_pct"),
    ("wpsr_gasoline_product_supplied_*.json",        None,        "gasoline_supplied_kbd"),
]


def load_series(glob: str, series_id: str | None) -> dict[str, float]:
    """Return {period: value} for the requested series."""
    files = list(TS_SOURCE.glob(glob))
    if not files:
        return {}
    d = json.loads(files[0].read_text())
    out: dict[str, float] = {}
    for r in d.get("response", {}).get("data", []):
        if series_id is not None and r.get("series") != series_id:
            continue
        period = r["period"]
        try:
            out[period] = float(r["value"])
        except (TypeError, ValueError):
            continue
    return out


COLS = [
    "period", "commercial_crude_kbbl", "refiner_input_kbd",
    "refinery_capacity_kbd", "refinery_util_pct", "gasoline_supplied_kbd",
]


def build_long_table() -> list[dict]:
    """Merge all series on `period`."""
    columns: dict[str, dict[str, float]] = {}
    for glob, sid, col in PIPE:
        columns[col] = load_series(glob, sid)
    periods = sorted(set().union(*[set(c) for c in columns.values()]))
    rows = []
    for p in periods:
        row = {"period": p}
        for col in columns:
            v = columns[col].get(p)
            row[col] = round(v, 2) if v is not None else None
        rows.append(row)
    return rows


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True, help="YYYY-MM-DD (Wed)")
    ap.add_argument("--instance-end",   required=True, help="YYYY-MM-DD (Wed)")
    args = ap.parse_args()

    rows = build_long_table()
    # Map period -> index for cumulative slicing.
    period_idx = {r["period"]: i for i, r in enumerate(rows)}

    # CLI args specify the Wed release window. Instance directory names use
    # the Friday data period_end (matched within 0-6 days of each Wed) so
    # evsandbox's no-future-leakage check sees timeseries.csv max period ==
    # dir name. When no matching Fri data exists yet (e.g., the most recent
    # Wed whose data hasn't published), the dir falls back to the Wed label
    # so the instance is still discoverable.
    start = parse_label(args.instance_start); end = parse_label(args.instance_end)
    for wed in iter_weeks(start, end):
        wed_label = wed.isoformat()
        match = None
        for p in rows:
            pd = dt.date.fromisoformat(p["period"])
            if 0 <= (pd - wed).days <= 6:
                match = p["period"]; break
        if match is None:
            dir_name = wed_label
            window = rows
            print(f"[warn] {wed_label}: no period within 0-6 days of Wed; "
                  f"falling back to Wed label", flush=True)
        else:
            dir_name = match
            window = rows[: period_idx[match] + 1]
        out_dir = INSTANCES / dir_name
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "timeseries.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            for r in window: w.writerow(r)
        print(f"[ok]  wed={wed_label} → instance={dir_name}: "
              f"{len(window)} weeks", flush=True)


# --- step: gt ------------------------------------------------------------
try:
    import pdfplumber
    HAVE_PDFPLUMBER = True
except ImportError:
    HAVE_PDFPLUMBER = False
    import subprocess


def extract_pdf_first_page(pdf_path: Path) -> str:
    """Return the text content of the Highlights PDF first page."""
    if HAVE_PDFPLUMBER:
        with pdfplumber.open(pdf_path) as pdf:
            return pdf.pages[0].extract_text() or ""
    # fallback: macOS-bundled `mdimport`-style? skip
    return ""


def direction(diff_kbbl: float) -> str:
    if diff_kbbl > 500: return "build"
    if diff_kbbl < -500: return "draw"
    return "flat"


def process(label: str) -> tuple[dict, str] | None:
    inst = INSTANCES / label
    ts_csv = inst / "timeseries.csv"
    if not ts_csv.exists(): return None
    rows = list(csv.DictReader(ts_csv.open()))
    if len(rows) < 2: return None
    last = rows[-1]; prior = rows[-2]

    def f(r, k):
        v = r.get(k)
        if v in (None, "", "None"): return None
        try: return float(v)
        except ValueError: return None

    crude_now = f(last, "commercial_crude_kbbl"); crude_prev = f(prior, "commercial_crude_kbbl")
    crude_diff = (crude_now - crude_prev) if (crude_now is not None and crude_prev is not None) else None
    crude_mmbbl = round(crude_diff / 1000, 1) if crude_diff is not None else None

    gt = {
        "commercial_crude_change_direction": direction(crude_diff) if crude_diff is not None else None,
        "commercial_crude_change_mmbbl":     crude_mmbbl,
        "refinery_util_pct":                 f(last, "refinery_util_pct"),
        "gasoline_supplied_kbd":             f(last, "gasoline_supplied_kbd"),
        # The verbatim Highlights paragraph serves as the LLM-judge reference for report.
        "report_reference":           None,
        "period_end":                        last["period"],
    }

    pdf = GT_SOURCE / f"{label}_highlights.pdf"
    pdf_text = extract_pdf_first_page(pdf) if pdf.exists() else ""
    # Heuristic: keep the body, drop heading lines (typically the first 3-5 lines).
    if pdf_text:
        # Find the first paragraph block of >= 2 sentences.
        lines = [ln.strip() for ln in pdf_text.splitlines() if ln.strip()]
        body_lines = []
        for ln in lines:
            if len(ln) > 30 or body_lines:
                body_lines.append(ln)
            if len(" ".join(body_lines)) > 600:
                break
        gt["report_reference"] = " ".join(body_lines)[:800]

    md = [
        f"# Evidence — week ending {label}\n",
        f"## Per-answer-field citations\n",
        f"- **commercial_crude_change_direction** -> `{gt['commercial_crude_change_direction']}` "
        f"(rule: |change| <= 500 kbbl is flat; sign otherwise)",
        f"- **commercial_crude_change_mmbbl** -> `{gt['commercial_crude_change_mmbbl']}` "
        f"(latest commercial_crude_kbbl {crude_now} minus prior {crude_prev}, /1000)",
        f"- **refinery_util_pct** -> `{gt['refinery_util_pct']}` (latest row)",
        f"- **gasoline_supplied_kbd** -> `{gt['gasoline_supplied_kbd']}` (latest row)",
        f"- **report** -> graded against the Highlights commentary below.\n",
        f"## Highlights commentary (verbatim, page 1 of `gt_source/{label}_highlights.pdf`)\n",
        gt['report_reference'] or "*(no text extracted)*",
    ]
    return gt, "\n".join(md)


def _step_gt() -> None:
    # CLI args are accepted for backward compat but ignored: instance dirs are
    # named by Friday period_end (created by `format.py timeseries`) and we just
    # walk INSTANCES directly. Each dir name IS the Friday data period.
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=False,
                    help="(ignored; kept for backward-compat CLI)")
    ap.add_argument("--instance-end",   required=False,
                    help="(ignored; kept for backward-compat CLI)")
    ap.parse_args()

    for inst in sorted(INSTANCES.iterdir()):
        if not inst.is_dir():
            continue
        label = inst.name
        out = process(label)
        if out is None: continue
        gt, ev = out
        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        # Append narrative-extract block from highlights PDF.
        pdf = GT_SOURCE / f"{label}_highlights.pdf"
        if not pdf.exists():
            pdf = GT_SOURCE / f"{label}_full.pdf"
        src_text, src_pages = load_source_text(pdf) if pdf.exists() else ("", [])
        if src_text:
            ev = ev.rstrip() + "\n\n" + build_narrative_md_block(
                f"gt_source/{pdf.name}", src_text, pages=src_pages,
            )
        (inst / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: dir={gt['commercial_crude_change_direction']} "
              f"crude_mmbbl={gt['commercial_crude_change_mmbbl']} util={gt['refinery_util_pct']}", flush=True)

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
