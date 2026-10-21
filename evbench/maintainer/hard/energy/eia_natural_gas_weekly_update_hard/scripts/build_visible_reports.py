"""Per-instance visible_reports.json -- prior HTMLs only."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE, INSTANCES  # noqa


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-dates", required=True)
    args = ap.parse_args()
    htmls = sorted(GT_SOURCE.glob("*.html"))
    labels = [h.stem for h in htmls]
    targets = [d.strip() for d in args.instance_dates.split(",") if d.strip()]
    for label in targets:
        out_dir = INSTANCES / label
        if not out_dir.exists(): continue
        prior = [d for d in labels if d < label]
        m = {
            "scenario_id": "eia_natural_gas_weekly_update_hard",
            "query_period": label,
            "visible_reports": [
                {"publication_thursday": d,
                 "path": f"../../gt_source/{d}.html",
                 "title": f"EIA Natural Gas Weekly Update -- {d}"}
                for d in prior
            ],
            "count": len(prior),
            "excludes_query_week": True,
        }
        (out_dir / "visible_reports.json").write_text(json.dumps(m, indent=2))
        print(f"[ok]   {label}: {len(prior)} prior reports in manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
