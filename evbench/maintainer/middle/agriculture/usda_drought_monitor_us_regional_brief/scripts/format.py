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
sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    TS_SOURCE, INSTANCES, CONUS_HEADLINE_THRESHOLD, iter_weeks, iso_label,
)
import json
import re
from bs4 import BeautifulSoup
from _common import (  # noqa: E402
    GT_SOURCE, INSTANCES, USDM_REGIONS, CONUS_HEADLINE_THRESHOLD,
    iter_weeks, iso_label,
)
MAINTAINER_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(MAINTAINER_ROOT / "lib"))
from narrative_extract import build_narrative_md_block, load_source_text  # noqa: E402


# --- step: timeseries ----------------------------------------------------


def national_headline(d0: float, d1: float, d2: float, d3: float, d4: float,
                      threshold: float = CONUS_HEADLINE_THRESHOLD) -> str:
    for cat, v in (("D4", d4), ("D3", d3), ("D2", d2), ("D1", d1), ("D0", d0)):
        if v >= threshold:
            return cat
    return "None"


def load_conus_rows() -> list[dict]:
    rows: list[dict] = []
    for p in sorted(TS_SOURCE.glob("conus_*.csv")):
        for raw in csv.DictReader(p.open()):
            d0 = float(raw["D0"] or 0); d1 = float(raw["D1"] or 0)
            d2 = float(raw["D2"] or 0); d3 = float(raw["D3"] or 0)
            d4 = float(raw["D4"] or 0); none_pct = float(raw["None"] or 0)
            obs = dt.datetime.strptime(raw["MapDate"], "%Y%m%d").date()
            iy, iw, _ = obs.isocalendar()
            rows.append({
                "observation_date":          obs.isoformat(),
                "iso_week":                  f"{iy:04d}-W{iw:02d}",
                "none_pct":                  round(none_pct, 2),
                "d0_pct":                    round(d0, 2),
                "d1_pct":                    round(d1, 2),
                "d2_pct":                    round(d2, 2),
                "d3_pct":                    round(d3, 2),
                "d4_pct":                    round(d4, 2),
                "national_headline_category": national_headline(d0, d1, d2, d3, d4),
            })
    rows.sort(key=lambda r: r["observation_date"])
    return rows


COLS = [
    "observation_date", "iso_week",
    "none_pct", "d0_pct", "d1_pct", "d2_pct", "d3_pct", "d4_pct",
    "national_headline_category",
]


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    rows = load_conus_rows()
    by_label = {r["iso_week"]: r for r in rows}
    ordered = [r["iso_week"] for r in rows]

    for y, w, _tue in iter_weeks(args.instance_start, args.instance_end):
        label = iso_label(y, w)
        if label not in by_label:
            print(f"[skip] {label}", flush=True); continue
        idx = ordered.index(label)
        window = ordered[: idx + 1]
        out_dir = INSTANCES / label
        out_dir.mkdir(parents=True, exist_ok=True)
        with (out_dir / "timeseries.csv").open("w", newline="") as f:
            w_ = csv.DictWriter(f, fieldnames=COLS)
            w_.writeheader()
            for lab in window:
                w_.writerow(by_label[lab])
        print(f"[ok]  {label}: {len(window)} weeks (headline={by_label[label]['national_headline_category']})", flush=True)


# --- step: gt ------------------------------------------------------------
# Degradation-language signal words. Counted within each region paragraph
# to pick the spotlight region.
DEGRADATION_RX = re.compile(
    r"\b(degrad|expand|intensif|worsen|deteriorat|expansion|dr(y|ier|iest)|"
    r"increase[d ] in dr|drought (?:expansion|spread)|hot,? dry|elevated heat)\b",
    re.IGNORECASE,
)
IMPROVEMENT_RX = re.compile(
    r"\b(improve|ease|reduction|alleviat|substantial rainfall|"
    r"heavy precipitation|significant moisture)\b",
    re.IGNORECASE,
)


def headline_for_csv_row(row: dict) -> str:
    d0 = float(row["d0_pct"] or 0); d1 = float(row["d1_pct"] or 0)
    d2 = float(row["d2_pct"] or 0); d3 = float(row["d3_pct"] or 0)
    d4 = float(row["d4_pct"] or 0)
    for cat, v in (("D4", d4), ("D3", d3), ("D2", d2), ("D1", d1), ("D0", d0)):
        if v >= CONUS_HEADLINE_THRESHOLD:
            return cat
    return "None"


def extract_region_chunks(html_path: Path) -> dict[str, str]:
    """Return {region: paragraph_text} for the 6 USDM regions."""
    if not html_path.exists(): return {}
    text = BeautifulSoup(html_path.read_bytes(), "lxml").get_text(" ", strip=True)
    out: dict[str, str] = {}
    for region in USDM_REGIONS:
        others = [r for r in USDM_REGIONS if r != region]
        pat = (rf"\b{re.escape(region)}\b\s+(.+?)"
               rf"(?=\b(?:{'|'.join(re.escape(r) for r in others)})\b|\Z)")
        m = re.search(pat, text, re.DOTALL)
        if m:
            chunk = m.group(1).strip()
            if len(chunk) > 1200:
                chunk = chunk[:1200].rsplit(". ", 1)[0] + "."
            out[region] = chunk
    return out


def pick_spotlight_region(region_chunks: dict[str, str]) -> tuple[str, int]:
    """Return (region, degradation_score) — the region with the most
    drought-expansion language this week. Ties broken by alphabetical order."""
    best = ("West", -1)
    for region, text in region_chunks.items():
        score = (
            len(DEGRADATION_RX.findall(text))
            - len(IMPROVEMENT_RX.findall(text))
        )
        if score > best[1]:
            best = (region, score)
    return best


def wow_change_direction(curr: dict, prior: dict | None) -> str:
    """Direction of D0+-or-worse total drought area vs prior week.
    ±0.5 pp is `stable`."""
    if prior is None: return "stable"
    try:
        cur = float(curr.get("d0_pct") or 0)
        pre = float(prior.get("d0_pct") or 0)
    except (TypeError, ValueError):
        return "stable"
    diff = cur - pre
    if diff > 0.5:  return "expanding"
    if diff < -0.5: return "contracting"
    return "stable"


def process(label: str) -> tuple[dict, str] | None:
    inst = INSTANCES / label
    ts_csv = inst / "timeseries.csv"
    if not ts_csv.exists(): return None
    rows = list(csv.DictReader(ts_csv.open()))
    if not rows: return None
    last = rows[-1]; prior = rows[-2] if len(rows) >= 2 else None
    obs = dt.date.fromisoformat(last["observation_date"])

    headline = last["national_headline_category"]
    direction = wow_change_direction(last, prior)

    chunks = extract_region_chunks(GT_SOURCE / f"{label}.html")
    spotlight, score = pick_spotlight_region(chunks)

    gt = {
        "national_headline_category":  headline,
        "spotlight_region":             spotlight,
        "national_dry_area_direction": direction,
        "d0_total_pct":                 float(last["d0_pct"] or 0),
        "as_of_date":                   obs.isoformat(),
    }

    md = [
        f"# Evidence — USDM National {label} (observation {obs})\n",
        f"## Per-answer-field citations\n",
        f"- **national_headline_category** -> `{headline}` "
        f"(rule: highest D-level with area ≥ {CONUS_HEADLINE_THRESHOLD}%)",
        f"- **spotlight_region** -> `{spotlight}` "
        f"(degradation-minus-improvement language count = {score})",
        f"- **national_dry_area_direction** -> `{direction}` "
        f"(d0_pct latest {last['d0_pct']} vs prior {prior['d0_pct'] if prior else 'n/a'}; "
        f"±0.5pp threshold)",
        f"- **d0_total_pct** -> {gt['d0_total_pct']} (latest cumulative national row)",
        f"- **report** -> graded against the Summary.aspx narrative below.",
        "",
        f"## Regional narratives (verbatim, from `gt_source/{label}.html`)\n",
    ]
    for region in USDM_REGIONS:
        para = chunks.get(region)
        if para:
            md.append(f"### {region}\n")
            md.append(f"> {para}\n")
    return gt, "\n".join(md)


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    for y, w, _tue in iter_weeks(args.instance_start, args.instance_end):
        label = iso_label(y, w)
        out = process(label)
        if out is None: continue
        gt, ev = out
        inst = INSTANCES / label
        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        # Append narrative-extract block (snapshot/verbatim/drivers/risks/outlook).
        src_text, src_pages = load_source_text(GT_SOURCE / f"{label}.html")
        if src_text:
            ev = ev + "\n\n" + build_narrative_md_block(
                f"gt_source/{label}.html", src_text, pages=src_pages,
            )
        (inst / "gt_evidence.md").write_text(ev)
        print(f"[ok]  {label}: hdr={gt['national_headline_category']} "
              f"spot={gt['spotlight_region']} dir={gt['national_dry_area_direction']}", flush=True)

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
