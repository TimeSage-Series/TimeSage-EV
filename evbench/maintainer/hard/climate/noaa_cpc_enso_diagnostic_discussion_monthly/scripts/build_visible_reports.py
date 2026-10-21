"""Build per-instance visible_reports.json — manifest of past ENSO DDs.

Strictly-before-query-month filter (V7). The query-month issue itself is
the ground-truth artifact and is NOT staged.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE, INSTANCES, iter_months  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    all_issues = sorted(
        p.stem for p in GT_SOURCE.glob("*.shtml")
        if len(p.stem) == 7 and p.stem[4] == "-"
    )

    n = 0
    for period in iter_months(args.instance_start, args.instance_end):
        folder = INSTANCES / period
        if not folder.exists():
            continue
        visible = [
            {"period": p, "path": f"../../gt_source/{p}.shtml"}
            for p in all_issues if p < period
        ]
        manifest = {
            "instance": period,
            "visible": visible,
            "count": len(visible),
            "excludes_query_month": True,
        }
        (folder / "visible_reports.json").write_text(
            json.dumps(manifest, indent=2)
        )
        n += 1
        print(f"[ok]  {period}: {len(visible)} past issues visible")
    print(f"[done] wrote {n} manifests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
