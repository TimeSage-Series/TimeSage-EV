#!/usr/bin/env python3
"""Append newly generated periods to the released corpus.

The pipeline writes into the data tree (`scenarios_wkspace/`, or $TIMESAGE_DATA_ROOT).
The released corpus in `evbench/scenarios/` is what evaluation reads, and its existing
periods are frozen: they are what the published results were scored on, and a
regenerated copy differs wherever the publisher has since revised history.

So this only ever adds periods after the last released one:

    instances/<p>/                 copied whole, once all four core files exist
    gt_source/, timeseries_source/ the files for <p>, named the way the
                                   released periods name theirs
    evbench/maintainer/…/scenario.json coverage.last and coverage.instances

    python evbench/maintainer/pipeline/publish_periods.py -t easy --dry-run
    python evbench/maintainer/pipeline/publish_periods.py -t easy

Run compare_reference.py first; publishing on top of a pipeline that no
longer reproduces the released periods would mix two different rule sets.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE = REPO_ROOT / "evbench" / "scenarios"
SCENARIOS_CODE = REPO_ROOT / "evbench" / "maintainer"
DATA_ROOT = Path(os.environ.get("TIMESAGE_DATA_ROOT", REPO_ROOT / "scenarios_wkspace"))

CORE = ("timeseries.csv", "gt_evidence.md", "instance.json", "ground_truth.json")
SOURCE_DIRS = ("gt_source", "timeseries_source")


def name_templates(folder: Path, periods: list[str]) -> set[str]:
    """`2025-W47.json` with period 2025-W47 -> `{p}.json`.

    Only per-period files yield a template; whole-history files and captures
    (`ao-dashboard-2026-05-12.html`) name no released period and are skipped.
    """
    out = set()
    if not folder.is_dir():
        return out
    for f in folder.iterdir():
        for p in sorted(periods, key=len, reverse=True):
            if p in f.name:
                out.add(f.name.replace(p, "{p}"))
                break
    return out


def find_source(data_dir: Path, name: str) -> Path | None:
    for cand in (data_dir / "source" / name.split(".")[0] / name,
                 *sorted((data_dir / "source").rglob(name))):
        if cand.is_file():
            return cand
    return None


def publish(ref: Path, dry_run: bool) -> list[str]:
    rel = ref.relative_to(REFERENCE)
    data = DATA_ROOT / rel
    released = sorted(d.name for d in (ref / "instances").iterdir() if d.is_dir())
    if not (data / "instances").is_dir():
        return []
    last = released[-1]
    candidates = sorted(d.name for d in (data / "instances").iterdir()
                        if d.is_dir() and d.name > last)

    added = []
    for p in candidates:
        src = data / "instances" / p
        missing = [f for f in CORE if not (src / f).is_file() or not (src / f).stat().st_size]
        if missing:
            print(f"  skip {p}: incomplete ({', '.join(missing)})")
            continue
        added.append(p)
        if dry_run:
            continue
        shutil.copytree(src, ref / "instances" / p)
        for sub in SOURCE_DIRS:
            for tpl in name_templates(ref / sub, released):
                name = tpl.replace("{p}", p)
                found = find_source(data, name)
                if found:
                    shutil.copy2(found, ref / sub / name)
                else:
                    print(f"  warn {p}: no source file {name} for {sub}/")

    if added and not dry_run:
        card_path = SCENARIOS_CODE / rel / "scenario.json"
        card = json.loads(card_path.read_text())
        cov = card.setdefault("coverage", {})
        cov["last"] = added[-1]
        cov["instances"] = len(released) + len(added)
        card_path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n")
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-t", "--tier", choices=["easy", "middle", "hard"])
    ap.add_argument("-s", "--scenario", action="append", help="repeatable")
    ap.add_argument("-n", "--dry-run", action="store_true")
    args = ap.parse_args()

    total = 0
    for ref in sorted(REFERENCE.glob("[!.]*/*/*")):
        tier, _domain, sid = ref.relative_to(REFERENCE).parts
        if (args.tier and tier != args.tier) or (args.scenario and sid not in args.scenario):
            continue
        added = publish(ref, args.dry_run)
        total += len(added)
        span = f"{added[0]} .. {added[-1]}" if added else "-"
        print(f"{len(added):3}  {sid[:50]:50} {span}")
    print(f"{'would add' if args.dry_run else 'added'} {total} periods")
    return 0


if __name__ == "__main__":
    sys.exit(main())
