#!/usr/bin/env python3
"""Compare regenerated instances against the released reference corpus.

The released `evbench/scenarios/` tree is what the paper was scored on. Before a
refreshed pipeline is trusted with new periods, re-running it over the released
periods must reproduce those files — or every difference must be explained.

    python evbench/maintainer/pipeline/compare_reference.py -t easy
    python evbench/maintainer/pipeline/compare_reference.py -s cboe_vix_volatility_regime_state -v
    python evbench/maintainer/pipeline/compare_reference.py -t easy --json out.json

Per instance file the verdict is one of

    same        byte-identical
    ws          identical after normalising whitespace and line endings
    diff        content differs
    missing     released file has no regenerated counterpart

ground_truth.json is additionally compared field by field; any answer field
whose value changed is listed, since that is what moves a score.

Exit status is 1 if any ground-truth value differs or any file is missing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE = REPO_ROOT / "evbench" / "scenarios"
DATA_ROOT = Path(os.environ.get("TIMESAGE_DATA_ROOT", REPO_ROOT / "scenarios_wkspace"))

FILES = ("ground_truth.json", "timeseries.csv", "gt_evidence.md",
         "instance.json")


def _norm(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", ln).strip()
            for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]


def compare_file(ref: Path, new: Path) -> str:
    if not new.exists():
        return "missing"
    a, b = ref.read_bytes(), new.read_bytes()
    if a == b:
        return "same"
    if ref.suffix == ".json":
        try:
            if json.loads(a) == json.loads(b):
                return "ws"
        except ValueError:
            pass
    if _norm(a.decode("utf-8", "replace")) == _norm(b.decode("utf-8", "replace")):
        return "ws"
    return "diff"


def compare_gt(ref: Path, new: Path) -> list[str]:
    """Answer fields whose value differs; `report` is a placeholder, skipped."""
    if not new.exists():
        return []
    try:
        a, b = json.loads(ref.read_text()), json.loads(new.read_text())
    except ValueError as exc:
        return [f"unparseable: {exc}"]
    out = []
    for key in sorted(set(a) | set(b)):
        if key == "report":
            continue
        if key not in b:
            out.append(f"{key}: dropped")
        elif key not in a:
            out.append(f"{key}: added ({b[key]!r})")
        elif a[key] != b[key]:
            out.append(f"{key}: {a[key]!r} -> {b[key]!r}")
    return out


def scenarios(args) -> list[Path]:
    out = []
    for sc in sorted(REFERENCE.glob("[!.]*/*/*")):
        tier, _domain, sid = sc.relative_to(REFERENCE).parts
        if args.tier and tier != args.tier:
            continue
        if args.scenario and sid not in args.scenario:
            continue
        out.append(sc)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-t", "--tier", choices=["easy", "middle", "hard"])
    ap.add_argument("-s", "--scenario", action="append", help="repeatable")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list every differing instance")
    ap.add_argument("--json", metavar="PATH", help="write the full result here")
    args = ap.parse_args()

    report, bad = {}, False
    for sc in scenarios(args):
        rel = sc.relative_to(REFERENCE)
        new_root = DATA_ROOT / rel / "instances"
        counts = {f: Counter() for f in FILES}
        flips, diffs = {}, {}
        periods = sorted(p.name for p in (sc / "instances").iterdir() if p.is_dir())
        for p in periods:
            for f in FILES:
                ref = sc / "instances" / p / f
                if not ref.exists():
                    continue
                verdict = compare_file(ref, new_root / p / f)
                counts[f][verdict] += 1
                if verdict in ("diff", "missing"):
                    diffs.setdefault(f, []).append(p)
            changed = compare_gt(sc / "instances" / p / "ground_truth.json",
                                 new_root / p / "ground_truth.json")
            if changed:
                flips[p] = changed
        missing = sum(c["missing"] for c in counts.values())
        bad |= bool(flips) or missing > 0
        report[str(rel)] = {"periods": len(periods),
                            "files": {f: dict(c) for f, c in counts.items()},
                            "gt_changed": flips, "differing": diffs}

        status = "GT!" if flips else ("MISS" if missing else
                 ("ok" if all(set(c) <= {"same", "ws"} for c in counts.values())
                  else "diff"))
        cells = []
        for f in FILES:
            c = counts[f]
            if not c:
                continue
            good = c["same"] + c["ws"]
            cells.append(f"{f.split('.')[0][:10]}={good}/{sum(c.values())}")
        print(f"{status:4} {rel.parts[-1][:48]:48} {' '.join(cells)}")
        for p, changed in flips.items():
            print(f"       gt {p}: {'; '.join(changed)}")
        if args.verbose:
            for f, ps in diffs.items():
                print(f"       {f}: {', '.join(ps[:8])}{' …' if len(ps) > 8 else ''}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
