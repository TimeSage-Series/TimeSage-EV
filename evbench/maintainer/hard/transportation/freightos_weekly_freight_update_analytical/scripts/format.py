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
from bs4 import BeautifulSoup
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, INSTANCES  # noqa: E402
from _common import GT_SOURCE, INSTANCES  # noqa: E402


# --- step: timeseries ----------------------------------------------------

# (column_key, regex with optional verb + pct group)
LANE_PATTERNS = [
    ("fbx_asia_uswc_pct_wow",
     re.compile(r"Asia\s*[-–]\s*US\s+West\s+Coast[^.]{0,80}?(increased|decreased|rose|fell|declined|climbed|gained|dropped|slipped|edged\s+up|edged\s+down)\s+(\d{1,3})\s*%", re.I)),
    ("fbx_asia_usec_pct_wow",
     re.compile(r"Asia\s*[-–]\s*US\s+East\s+Coast[^.]{0,80}?(increased|decreased|rose|fell|declined|climbed|gained|dropped|slipped|edged\s+up|edged\s+down)\s+(\d{1,3})\s*%", re.I)),
    ("fbx_asia_neur_pct_wow",
     re.compile(r"Asia\s*[-–]\s*N\.\s*Europe[^.]{0,80}?(increased|decreased|rose|fell|declined|climbed|gained|dropped|slipped|edged\s+up|edged\s+down)\s+(\d{1,3})\s*%", re.I)),
    ("fbx_asia_med_pct_wow",
     re.compile(r"Asia\s*[-–]\s*Mediterranean[^.]{0,80}?(increased|decreased|rose|fell|declined|climbed|gained|dropped|slipped|edged\s+up|edged\s+down)\s+(\d{1,3})\s*%", re.I)),
    ("fai_china_na_pct_wow",
     re.compile(r"China\s*[-–]\s*N\.\s*America[^.]{0,80}?(increased|decreased|rose|fell|declined|climbed|gained|dropped|slipped|edged\s+up|edged\s+down)\s+(\d{1,3})\s*%", re.I)),
    ("fai_china_neur_pct_wow",
     re.compile(r"China\s*[-–]\s*N\.\s*Europe[^.]{0,80}?(increased|decreased|rose|fell|declined|climbed|gained|dropped|slipped|edged\s+up|edged\s+down)\s+(\d{1,3})\s*%", re.I)),
    ("fai_neur_na_pct_wow",
     re.compile(r"N\.\s*Europe\s*[-–]\s*N\.\s*America[^.]{0,80}?(increased|decreased|rose|fell|declined|climbed|gained|dropped|slipped|edged\s+up|edged\s+down)\s+(\d{1,3})\s*%", re.I)),
]

NEG_VERBS = {"decreased", "fell", "declined", "dropped", "slipped", "edged down"}

COLS = [
    "publication_date",
    "fbx_asia_uswc_pct_wow",
    "fbx_asia_usec_pct_wow",
    "fbx_asia_neur_pct_wow",
    "fbx_asia_med_pct_wow",
    "fai_china_na_pct_wow",
    "fai_china_neur_pct_wow",
    "fai_neur_na_pct_wow",
]

WOW_BOUND = (-90.0, 90.0)


def page_text(html_path: Path) -> str:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"),
                         "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def parse_one(html_path: Path) -> dict:
    text = page_text(html_path)
    out: dict = {}
    for col, pat in LANE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        verb = m.group(1).lower().strip()
        try:
            pct = float(m.group(2))
        except ValueError:
            continue
        if verb in NEG_VERBS or verb.startswith("edged down"):
            pct = -pct
        if WOW_BOUND[0] <= pct <= WOW_BOUND[1]:
            out[col] = pct
    return out


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=24)
    args = ap.parse_args()

    parsed: dict[str, dict] = {}
    for f in sorted(TS_SOURCE.glob("freightos_*.html")):
        m = re.match(r"freightos_(\d{4}-\d{2}-\d{2})\.html$", f.name)
        if not m:
            continue
        date = m.group(1)
        row = parse_one(f)
        if not row:
            print(f"[parse-skip] {date}", flush=True)
            continue
        row["publication_date"] = date
        parsed[date] = row

    if not parsed:
        print("[err] no parseable HTML found", flush=True)
        return

    # cumulative window = all parsed dates ≤ each instance date
    out = Path(__file__).parent / "_parsed_metrics.json"
    out.write_text(json.dumps(parsed, indent=2))
    dates = sorted(parsed)
    instance_dates = dates[-args.count:]  # use the N most recent as instance set
    print(f"[plan] {len(instance_dates)} instance dates", flush=True)

    built = 0
    for d in instance_dates:
        window = [parsed[p] for p in dates if p <= d]
        inst = INSTANCES / d
        inst.mkdir(parents=True, exist_ok=True)
        with (inst / "timeseries.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            for r in window:
                w.writerow({k: r.get(k, "") for k in COLS})
        built += 1
        print(f"[ok] {d}: {len(window)} rows", flush=True)

    print(f"\nSummary: built={built} parsed={len(parsed)}", flush=True)


# --- step: gt ------------------------------------------------------------
OCEAN_KEYS = ["fbx_asia_uswc_pct_wow", "fbx_asia_usec_pct_wow",
              "fbx_asia_neur_pct_wow", "fbx_asia_med_pct_wow"]
AIR_KEYS   = ["fai_china_na_pct_wow", "fai_china_neur_pct_wow",
              "fai_neur_na_pct_wow"]

LANE_DISPLAY = {
    "fbx_asia_uswc_pct_wow": "asia_uswc",
    "fbx_asia_usec_pct_wow": "asia_usec",
    "fbx_asia_neur_pct_wow": "asia_neur",
    "fbx_asia_med_pct_wow":  "asia_med",
    "fai_china_na_pct_wow":  "china_na_air",
    "fai_china_neur_pct_wow":"china_neur_air",
    "fai_neur_na_pct_wow":   "neur_na_air",
}

DRIVER_KEYWORDS: list[tuple[str, str]] = [
    (r"\bIran\b|\bHormuz\b|\bRed\s+Sea\b|\bgeopolit|\bwar\b|\bsurcharge\b",  "geopolitical"),
    (r"\bLunar\s+New\s+Year\b|\bLNY\b|\bpeak\s+season\b|\bseasonal\b",      "demand_seasonality"),
    (r"\bcapacity\b|\bovercapacity\b|\bvessel\s+deliveries\b|\bfleet\b",    "capacity_dynamics"),
    (r"\bfuel\b|\bbunker\b|\bdiesel\b",                                     "fuel_cost"),
    (r"\bTrump\b|\btariff\b|\btrade\s+policy\b|\bSection\s+\d+\b",          "trade_policy"),
    (r"\btyphoon\b|\bstorm\b|\bweather\b|\bhurricane\b",                    "weather_disruption"),
]
PRIMARY_OK = {d for _, d in DRIVER_KEYWORDS} | {"other"}

OUTLOOK_POS = re.compile(r"\b(?:recover|gain|increase|momentum|firm|stable|easing)\b", re.I)
OUTLOOK_NEG = re.compile(r"\b(?:risk|decline|weak|slow|drop|cautious|deteriorat|concern)\b", re.I)


def page_text__gt(p: Path) -> str:
    soup = BeautifulSoup(p.read_text(encoding="utf-8", errors="replace"),
                         "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def find_analysis_block(text: str) -> str:
    # The body section usually has "Analysis" as a header word; otherwise just
    # take the largest chunk between the first "%" sign and the unsubscribe text.
    i = text.find("Analysis")
    if i < 0:
        return text[:3000]
    j = text.find("Join 65,000", i)
    if j < 0:
        j = i + 4000
    return text[i:j]


def derive_direction(values: list[float]) -> str:
    if not values:
        return "stable"
    pos = sum(1 for v in values if v > 1)
    neg = sum(1 for v in values if v < -1)
    if pos >= neg + 2:
        return "rising"
    if neg >= pos + 2:
        return "falling"
    if pos and neg:
        return "mixed"
    return "stable"


def derive_drivers(text: str) -> tuple[str, list[str]]:
    hits: list[str] = []
    for pat, label in DRIVER_KEYWORDS:
        if re.search(pat, text) and label not in hits:
            hits.append(label)
    if not hits:
        return "other", []
    return hits[0], hits[1:3]


def derive_outlook_tone(text: str) -> str:
    pos = len(OUTLOOK_POS.findall(text))
    neg = len(OUTLOOK_NEG.findall(text))
    if pos > neg + 1:
        return "positive"
    if neg > pos + 1:
        return "negative"
    return "cautious"


def rank_lanes(row: dict) -> tuple[list[str], list[str]]:
    pairs = [(LANE_DISPLAY[k], row[k]) for k in LANE_DISPLAY if row.get(k) is not None]
    if not pairs:
        return [], []
    pairs.sort(key=lambda kv: kv[1], reverse=True)
    top = [k for k, v in pairs if v > 0][:2]
    bot = [k for k, v in pairs[::-1] if v < 0][:2]
    return top, bot


def take_quotes(analysis: str, n: int = 3) -> list[str]:
    sents = re.split(r"(?<=[\.\?\!])\s+", analysis)
    out: list[str] = []
    for s in sents:
        s = s.strip()
        if 60 <= len(s) <= 400 and any(k in s.lower() for k in
                                       ("rate", "carrier", "demand", "war",
                                        "hormuz", "tariff", "capacity", "fuel",
                                        "outlook", "expect", "season")):
            out.append(s)
        if len(out) >= n:
            break
    if len(out) < n:
        for s in sents:
            if 40 <= len(s) <= 400 and s not in out:
                out.append(s)
            if len(out) >= n:
                break
    return out[:6]


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=24)
    args = ap.parse_args()

    parsed_metrics = json.loads(
        (Path(__file__).parent / "_parsed_metrics.json").read_text())
    dates = sorted(parsed_metrics)
    instance_dates = dates[-args.count:]

    built = 0
    for d in instance_dates:
        html = GT_SOURCE / f"freightos_{d}.html"
        if not html.exists():
            html = (Path(__file__).parent.parent / "timeseries_source"
                    / f"freightos_{d}.html")
        if not html.exists():
            print(f"[skip] {d}: no html", flush=True)
            continue
        text = page_text__gt(html)
        analysis = find_analysis_block(text)

        row = parsed_metrics[d]
        ocean_vals = [row[k] for k in OCEAN_KEYS if row.get(k) is not None]
        air_vals   = [row[k] for k in AIR_KEYS   if row.get(k) is not None]

        dom, sec = derive_drivers(analysis)
        top, bot = rank_lanes(row)
        quotes = take_quotes(analysis, 3)

        gt = {
            "ocean_rate_direction": derive_direction(ocean_vals),
            "air_rate_direction":   derive_direction(air_vals),
            "dominant_driver":      dom,
            "secondary_drivers":    sec,
            "lanes_with_largest_increase": top,
            "lanes_with_largest_decrease": bot,
            "outlook_tone":         derive_outlook_tone(analysis),
            "supporting_evidence":  [
                {"section": "Analysis", "quote": q} for q in quotes
            ],
        }

        inst = INSTANCES / d
        inst.mkdir(parents=True, exist_ok=True)
        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2))

        ev_lines = [
            f"# Freightos Weekly Freight Update — {d}",
            f"Source: `gt_source/freightos_{d}.html`\n",
            "## Analysis quotes\n",
        ]
        for q in quotes:
            ev_lines.append(f"> {q}\n")
        ev_lines.append("\n## Driver heuristic")
        ev_lines.append(f"- dominant: `{dom}`  secondary: `{sec}`")
        (inst / "gt_evidence.md").write_text("\n".join(ev_lines))

        built += 1
        print(f"[ok] {d}: ocean={gt['ocean_rate_direction']} air={gt['air_rate_direction']} drv={dom}", flush=True)

    print(f"\nSummary: built={built}", flush=True)

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
