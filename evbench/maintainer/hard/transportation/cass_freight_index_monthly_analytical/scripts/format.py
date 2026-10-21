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
from _common import TS_SOURCE, INSTANCES, iter_months, month_label  # noqa: E402


# --- step: timeseries ----------------------------------------------------

# Plausibility bounds
SHIP_RANGE = (0.70, 1.70)
EXP_RANGE  = (1.30, 4.50)
YOY_RANGE  = (-40.0, 40.0)

# Token after an anchor: either a decimal level (1.007) or a signed % (-4.5%)
TOK_RE = re.compile(r"(-?\d+\.\d+)\s*%?")


def page_text(html_path: Path) -> str:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"),
                         "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def cells_after(text: str, anchor: str, n: int) -> list[float]:
    """Return up to n numeric tokens immediately after `anchor`."""
    i = text.find(anchor)
    if i < 0:
        return []
    tail = text[i + len(anchor): i + len(anchor) + 200]
    return [float(m.group(1)) for m in TOK_RE.finditer(tail)][:n]


def parse_one(html_path: Path) -> dict | None:
    text = page_text(html_path)
    ship_cells = cells_after(text, "Shipments", 5)
    exp_cells  = cells_after(text, "Cass Freight Index - Expenditures", 5)
    if len(ship_cells) < 2 or len(exp_cells) < 2:
        return None
    ship_idx, ship_yoy = ship_cells[0], ship_cells[1]
    exp_idx,  exp_yoy  = exp_cells[0],  exp_cells[1]
    if not (SHIP_RANGE[0] <= ship_idx <= SHIP_RANGE[1]):
        return None
    if not (EXP_RANGE[0]  <= exp_idx  <= EXP_RANGE[1]):
        return None
    if not (YOY_RANGE[0]  <= ship_yoy <= YOY_RANGE[1]):
        return None
    if not (YOY_RANGE[0]  <= exp_yoy  <= YOY_RANGE[1]):
        return None
    return {
        "shipments_index":      round(ship_idx, 3),
        "shipments_yoy_pct":    round(ship_yoy, 2),
        "expenditures_index":   round(exp_idx, 3),
        "expenditures_yoy_pct": round(exp_yoy, 2),
        "inferred_rate_per_shipment": round(exp_idx / ship_idx, 4),
    }


COLS = [
    "period",
    "shipments_index",
    "shipments_yoy_pct",
    "expenditures_index",
    "expenditures_yoy_pct",
    "inferred_rate_per_shipment",
]


def _step_timeseries() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", default="2024-04")
    ap.add_argument("--instance-end",   default="2026-03")
    args = ap.parse_args()

    parsed: dict[str, dict] = {}
    for html in sorted(TS_SOURCE.glob("cass_*.html")):
        m = re.match(r"cass_(\d{4}-\d{2})\.html$", html.name)
        if not m:
            continue
        label = m.group(1)
        row = parse_one(html)
        if row is None:
            print(f"[parse-skip] {label}", flush=True)
            continue
        row["period"] = label
        parsed[label] = row

    out = Path(__file__).parent / "_parsed_metrics.json"
    out.write_text(json.dumps(parsed, indent=2))

    ordered = sorted(parsed)
    built = 0
    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        if label not in parsed:
            continue
        window = [parsed[p] for p in ordered if p <= label]
        inst = INSTANCES / label
        inst.mkdir(parents=True, exist_ok=True)
        with (inst / "timeseries.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            for r in window:
                w.writerow({k: r.get(k) for k in COLS})
        built += 1
        print(f"[ok] {label}: {len(window)} rows", flush=True)

    print(f"\nSummary: built={built} parsed={len(parsed)}", flush=True)


# --- step: gt ------------------------------------------------------------
DRIVER_VOCAB = [
    "supply_constraint", "demand_recovery", "demand_weakness",
    "capacity_dynamics", "fuel_costs", "regulatory_change",
    "e_commerce_shift", "manufacturing_activity", "retail_inventory",
    "intermodal_substitution", "other",
]

# Keyword → controlled vocab label
DRIVER_KEYWORDS: list[tuple[str, str]] = [
    (r"\bcapacity\b|\btightening\b|\btight\b|\bClass\s?8\b",   "capacity_dynamics"),
    (r"\bdriver\s+shortage\b|\bCDL\b|\bELD\b|\bregulation\b",  "regulatory_change"),
    (r"\bfuel\b|\bdiesel\b|\bbunker\b",                        "fuel_costs"),
    (r"\bmanufacturing\b|\bindustrial\b|\bISM\b",              "manufacturing_activity"),
    (r"\bretail\b|\bconsumer\b|\binventor",                    "retail_inventory"),
    (r"\bintermodal\b",                                        "intermodal_substitution"),
    (r"\be[- ]?commerce\b|\bparcel\b",                         "e_commerce_shift"),
    (r"\bdemand\s+(?:recovery|rising|growth|strength)\b|\brecover",  "demand_recovery"),
    (r"\bdemand\s+(?:weak|soft|declin)|\bsoft(?:er|ening)?\b", "demand_weakness"),
    (r"\bsupply\s+chain\b|\bsupply\s+disruption\b",            "supply_constraint"),
]

OUTLOOK_POS_PAT = re.compile(
    r"\b(?:rise|gain|increase|recovery|stronger|firm|tighten|tightening|"
    r"continued\s+growth|early\s+cycle|momentum)\b", re.I)
OUTLOOK_NEG_PAT = re.compile(
    r"\b(?:decline|fall|deteriorat|weak|soft|caution|risk|headwind|"
    r"contract|slow|drag)\b", re.I)

SECTION_HEADS = [
    "Cass Freight Index® - Shipments",
    "Cass Freight Index® – Shipments",
    "Cass Freight Index - Shipments",
    "Cass Freight Index - Expenditures",
    "Cass Freight Index® - Expenditures",
    "Cass Freight Index® – Expenditures",
    "Cass Inferred Freight Rates",
    "Truckload Linehaul Index",
    "Closing Thoughts",
    "About the Cass Freight Index",
]


def page_html(html_path: Path) -> BeautifulSoup:
    return BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"),
                         "html.parser")


def extract_sections(soup: BeautifulSoup) -> list[tuple[str, list[str]]]:
    """Return [(section_name, [paragraph, ...]), ...]."""
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        tag.decompose()
    paragraphs = []
    for p in soup.find_all(["p", "li"]):
        t = p.get_text(" ", strip=True)
        t = re.sub(r"\s+", " ", t)
        if 40 <= len(t) <= 1200:
            paragraphs.append(t)

    text = " ".join(paragraphs)
    sections: list[tuple[str, list[str]]] = []
    anchors: list[tuple[int, str]] = []
    for h in SECTION_HEADS:
        i = text.find(h)
        if i >= 0:
            anchors.append((i, h))
    anchors.sort()
    if not anchors:
        return [("Body", paragraphs)]

    for idx, (pos, head) in enumerate(anchors):
        end = anchors[idx + 1][0] if idx + 1 < len(anchors) else len(text)
        body = text[pos + len(head): end]
        body_paras = [
            p.strip()
            for p in re.split(r"(?<=[\.\!\?])\s+(?=[A-Z])", body)
            if 40 <= len(p.strip()) <= 600
        ]
        sections.append((head, body_paras[:6]))
    return sections


def derive_headline_direction(ship_yoy: float, exp_yoy: float) -> str:
    if ship_yoy < -1 and exp_yoy < -1:
        return "contracting"
    if ship_yoy > 1 and exp_yoy > 1:
        return "expanding"
    return "transitioning"


def derive_rate_environment(ship_yoy: float, exp_yoy: float, inferred_rate_chg: float) -> str:
    diff = exp_yoy - ship_yoy
    if diff > 2 or inferred_rate_chg > 1:
        return "rates_rising"
    if diff < -2 or inferred_rate_chg < -1:
        return "rates_falling"
    return "rates_stable"


def derive_drivers(text: str, max_n: int = 3) -> list[str]:
    found: list[str] = []
    for pat, label in DRIVER_KEYWORDS:
        if re.search(pat, text, re.I) and label not in found:
            found.append(label)
        if len(found) >= max_n:
            break
    return found or ["other"]


def derive_outlook_tone(text: str) -> str:
    pos = len(OUTLOOK_POS_PAT.findall(text))
    neg = len(OUTLOOK_NEG_PAT.findall(text))
    if pos > neg + 1:
        return "positive"
    if neg > pos + 1:
        return "negative"
    return "cautious"


def build_for_period(label: str, html_path: Path, parsed: dict) -> tuple[dict, str]:
    soup = page_html(html_path)
    sections = extract_sections(soup)
    flat_text = " ".join(p for _, ps in sections for p in ps)

    ship_yoy = parsed.get("shipments_yoy_pct", 0.0)
    exp_yoy  = parsed.get("expenditures_yoy_pct", 0.0)

    gt = {
        "headline_direction": derive_headline_direction(ship_yoy, exp_yoy),
        "key_drivers": derive_drivers(flat_text),
        "outlook_tone": derive_outlook_tone(flat_text),
        "rate_environment": derive_rate_environment(ship_yoy, exp_yoy, 0.0),
        "supporting_evidence": [],
    }

    ev_lines: list[str] = [f"# Cass Transportation Index Report — {label}"]
    ev_lines.append(f"Source: `gt_source/cass_{label}.html`\n")
    for head, paras in sections:
        if not paras:
            continue
        ev_lines.append(f"\n## {head}\n")
        for p in paras[:3]:
            ev_lines.append(f"> {p}\n")
            if len(gt["supporting_evidence"]) < 6:
                gt["supporting_evidence"].append({"section": head, "quote": p})

    return gt, "\n".join(ev_lines)


def _step_gt() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", default="2024-04")
    ap.add_argument("--instance-end",   default="2026-03")
    args = ap.parse_args()

    parsed_path = Path(__file__).parent / "_parsed_metrics.json"
    if not parsed_path.exists():
        print("[err] run `format.py timeseries` first to produce _parsed_metrics.json",
              flush=True)
        return
    parsed = json.loads(parsed_path.read_text())

    built = 0
    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        if label not in parsed:
            continue
        html = TS_SOURCE / f"cass_{label}.html"
        if not html.exists():
            continue
        inst = INSTANCES / label
        inst.mkdir(parents=True, exist_ok=True)
        gt, evidence = build_for_period(label, html, parsed[label])
        (inst / "ground_truth.json").write_text(json.dumps(gt, indent=2))
        (inst / "gt_evidence.md").write_text(evidence)
        built += 1
        print(f"[ok] {label}: dir={gt['headline_direction']}  "
              f"drivers={gt['key_drivers']}  tone={gt['outlook_tone']}",
              flush=True)

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
