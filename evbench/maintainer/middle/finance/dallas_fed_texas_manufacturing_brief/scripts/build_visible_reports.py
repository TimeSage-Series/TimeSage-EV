"""Per-instance visible_reports.json -- prior HTMLs only."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE, INSTANCES, iter_months, month_label  # noqa


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    args = ap.parse_args()
    htmls = sorted(GT_SOURCE.glob("*.html"))
    labels = [h.stem for h in htmls]
    for y, m in iter_months(args.start, args.end):
        label = month_label(y, m)
        out_dir = INSTANCES / label
        if not out_dir.exists(): continue
        prior = [d for d in labels if d < label]
        m_ = {"scenario_id": "dallas_fed_texas_manufacturing_brief",
              "query_period": label,
              "visible_reports": [{"data_month": d, "path": f"../../gt_source/{d}.html",
                                   "title": f"Dallas Fed TMOS -- {d}"}
                                  for d in prior],
              "count": len(prior),
              "excludes_query_month": True}
        (out_dir / "visible_reports.json").write_text(json.dumps(m_, indent=2))
        print(f"[ok]   {label}: {len(prior)} prior reports")
    return 0


if __name__ == "__main__":
    sys.exit(main())
