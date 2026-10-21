"""Build per-instance visible_reports.json — manifest of past NCEI briefs
that the agent is allowed to read at query time.

Convention follows the healthcare WHO scenario and the climate ONI / NSIDC
scenarios: the instance directory carries ONLY a manifest pointing back to
the scenario-level `gt_source/`. The eval harness stages the listed files
into `/root/gt_source/` at runtime.

V7 guarantee: the manifest STRICTLY excludes the query-month brief itself.
The agent has past briefs (cumulative trend context) but never the answer.

Usage:
    python3 scripts/build_visible_reports.py --instance-start 2024-05 \
                                              --instance-end   2026-04
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    GT_SOURCE, INSTANCES,
    iter_periods, period_to_yyyymm, yyyymm_to_period,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    # Enumerate all NCEI HTML files present in gt_source/.
    all_html = sorted(GT_SOURCE.glob("national-climate-*.html"))
    pairs: list[tuple[str, Path]] = []
    for p in all_html:
        # Match 'national-climate-YYYYMM.html'; reject annual rollups (MM=13).
        stem = p.stem  # "national-climate-202401"
        if not stem.startswith("national-climate-"):
            continue
        yyyymm = stem[len("national-climate-"):]
        if len(yyyymm) != 6 or not yyyymm.isdigit():
            continue
        if int(yyyymm[4:6]) > 12:
            continue   # 13 = annual rollup, out of scope
        pairs.append((yyyymm_to_period(yyyymm), p))
    pairs.sort()

    n_written = 0
    for inst in iter_periods(args.instance_start, args.instance_end):
        out_dir = INSTANCES / inst
        if not out_dir.exists():
            print(f"[skip] {inst}: instance dir missing", flush=True)
            continue
        # STRICTLY-before filter (V7).
        visible = [
            {"period": pp, "path": f"../../gt_source/{path.name}"}
            for (pp, path) in pairs if pp < inst
        ]
        manifest = {
            "instance":           inst,
            "query_month":        inst,
            "visible":            visible,
            "count":              len(visible),
            "excludes_query_month": True,
            "note": (
                "These are NOAA NCEI monthly global climate briefs published "
                "BEFORE the query month. The query-month brief is the GROUND "
                "TRUTH and is intentionally not included here."
            ),
        }
        (out_dir / "visible_reports.json").write_text(json.dumps(manifest,
                                                                 indent=2))
        n_written += 1
        print(f"[ok]  {inst}: {len(visible)} visible past briefs", flush=True)
    print(f"\n[done] wrote {n_written} manifests", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
