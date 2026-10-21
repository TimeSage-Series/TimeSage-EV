"""Build per-instance visible_reports.json — manifest of past WHO cholera SitRep PDFs.

Same pattern as scenario 2: instance dir holds only the manifest, not copies.
The manifest points back to scenario-level gt_source/ via relative path. Eval
harness stages the listed files into /root/gt_source/ at runtime.

A SitRep PDF for month M is considered 'visible' at instance M if its period
end falls STRICTLY BEFORE the period end of M. The agent never sees the
current-month SitRep PDF directly — only the cumulative timeseries.csv row
and the prior PDFs.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE, INSTANCES, iter_months, month_label, last_day_of_month  # noqa


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    all_sources: list[tuple[dt.date, str, Path]] = []
    for src in sorted(GT_SOURCE.glob("*.pdf")):
        sy, sm = src.stem.split("-M"); sy, sm = int(sy), int(sm)
        all_sources.append((last_day_of_month(sy, sm), src.stem, src))
    all_sources.sort()

    for y, m, last in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        out_dir = INSTANCES / label
        if not out_dir.exists():
            print(f"[skip] {label}: instance dir missing", flush=True); continue
        visible = [
            {"label": s_label, "path": f"../../gt_source/{s_path.name}",
             "period_end": s_end.isoformat()}
            for (s_end, s_label, s_path) in all_sources
            if s_end < last
        ]
        manifest = {
            "instance": label,
            "query_period_end": last.isoformat(),
            "visible": visible,
            "count": len(visible),
        }
        (out_dir / "visible_reports.json").write_text(json.dumps(manifest, indent=2))
        print(f"[ok]  {label}: {len(visible)} visible reports", flush=True)


if __name__ == "__main__":
    main()
