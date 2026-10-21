#!/usr/bin/env python3
"""Restore the scenario source binaries (PDF/XLS) from Hugging Face.

The report PDFs and Excel workbooks under `<data tree>/*/*/*/gt_source/` and
`<data tree>/*/*/*/timeseries_source/` are 2.3 GB and live in a Hugging Face
dataset rather than in git. Everything needed to *run* an evaluation —
`instances/`, `environment/`, and the derived `gt_evidence.md` — is in git, so
this download is only required when you want to:

  * re-run a scenario's `scripts/format.py` to regenerate ground truth, or
  * let an agent read the original source reports inside the sandbox
    (`evsandbox` copies `gt_source/` into the agent's working dir).

Usage:
    python evbench/maintainer/corpus/fetch_gt_source.py                  # everything
    python evbench/maintainer/corpus/fetch_gt_source.py --tier hard      # one tier
    python evbench/maintainer/corpus/fetch_gt_source.py --scenario eia_wpsr_weekly_petroleum_brief
    python evbench/maintainer/corpus/fetch_gt_source.py --verify-only    # checksum what's on disk

Requires `huggingface_hub` (`pip install huggingface_hub`).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def local_path(rel: str) -> Path:
    """Where a manifest entry lives on disk.

    Manifest keys keep the Hugging Face layout `scenarios/<tier>/…`. Locally the
    finished easy tier is evbench/scenarios/ and the rest is scenarios_unfinished/.
    """
    _, tier, *rest = Path(rel).parts
    root = REPO_ROOT / "evbench" / "scenarios" if tier == "easy" else REPO_ROOT / "scenarios_unfinished"
    return root.joinpath(tier, *rest)
MANIFEST = Path(__file__).resolve().parent / "gt_source_manifest.json"

_CHUNK = 1 << 20


def load_manifest() -> dict:
    if not MANIFEST.exists():
        sys.exit(f"manifest not found: {MANIFEST}")
    return json.loads(MANIFEST.read_text())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def select(files: dict, tier: str | None, scenario: str | None) -> dict:
    """Filter manifest entries by tier and/or scenario id.

    Paths are `scenarios/<tier>/<domain>/<scenario_id>/<dir>/<file>`.
    """
    out = {}
    for rel, meta in files.items():
        parts = Path(rel).parts
        if len(parts) < 5:
            continue
        if tier and parts[1] != tier:
            continue
        if scenario and parts[3] != scenario:
            continue
        out[rel] = meta
    return out


def check(rel: str, meta: dict) -> str:
    """Return 'ok', 'missing', or 'corrupt' for one manifest entry."""
    p = local_path(rel)
    if not p.exists():
        return "missing"
    if p.stat().st_size != meta["size"] or sha256(p) != meta["sha256"]:
        return "corrupt"
    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tier", choices=["easy", "middle", "hard"])
    ap.add_argument("--scenario", help="scenario id (directory name)")
    ap.add_argument("--verify-only", action="store_true",
                    help="checksum local files, download nothing")
    ap.add_argument("--force", action="store_true",
                    help="re-download even if the local file already verifies")
    ap.add_argument("--dataset", help="override the dataset repo id")
    args = ap.parse_args()

    man = load_manifest()
    dataset = args.dataset or man["dataset"]
    wanted = select(man["files"], args.tier, args.scenario)
    if not wanted:
        sys.exit("no manifest entries matched those filters")

    states = {rel: check(rel, meta) for rel, meta in wanted.items()}
    n_ok = sum(1 for s in states.values() if s == "ok")
    todo = [r for r, s in states.items() if s != "ok" or args.force]

    print(f"manifest: {len(wanted)} files  |  verified: {n_ok}  "
          f"missing: {sum(1 for s in states.values() if s == 'missing')}  "
          f"corrupt: {sum(1 for s in states.values() if s == 'corrupt')}")

    if args.verify_only:
        for rel, s in sorted(states.items()):
            if s != "ok":
                print(f"  {s:8s} {rel}")
        return 0 if n_ok == len(wanted) else 1

    if not todo:
        print("nothing to do — all files present and verified")
        return 0

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        sys.exit("huggingface_hub is required: pip install huggingface_hub")

    bytes_todo = sum(wanted[r]["size"] for r in todo)
    print(f"downloading {len(todo)} files ({bytes_todo / 1e6:.0f} MB) "
          f"from {dataset} …")

    failed = []
    for i, rel in enumerate(sorted(todo), 1):
        dest = local_path(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            cached = hf_hub_download(repo_id=dataset, repo_type="dataset",
                                     filename=rel)
        except Exception as exc:                            # network, auth, 404
            failed.append((rel, str(exc)))
            print(f"  [{i}/{len(todo)}] FAIL {rel}: {exc}")
            continue
        shutil.copyfile(cached, dest)
        state = check(rel, wanted[rel])
        if state != "ok":
            failed.append((rel, f"checksum {state}"))
            print(f"  [{i}/{len(todo)}] BAD  {rel}: {state}")
        elif i % 50 == 0 or i == len(todo):
            print(f"  [{i}/{len(todo)}] …")

    if failed:
        print(f"\n{len(failed)} file(s) failed:")
        for rel, why in failed[:20]:
            print(f"  {rel}: {why}")
        return 1
    print(f"\ndone — {len(todo)} file(s) restored and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
