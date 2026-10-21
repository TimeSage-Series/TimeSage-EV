"""Build per-instance visible_reports.json — manifest of past PAHO bulletins.

Same manifest pattern as scenarios 1 and 2: instance directories hold
only the manifest, not copies of past PDFs. The manifest points back to
the scenario-level ``gt_source/`` via relative path. The eval harness
stages the listed files into ``/root/gt_source/`` at runtime.

Ordering is by Saturday of the LATTER week (w2) of each bi-weekly issue,
which is the same anchor used by the cumulative timeseries.csv. V7
information isolation is enforced: only issues whose week_ending is
STRICTLY BEFORE the query issue's week_ending are listed.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (GT_SOURCE, INSTANCES, iter_biweekly_issues,
                     biweekly_label, parse_biweekly_label, paho_saturday)  # noqa


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    all_sources: list[tuple[dt.date, str, Path]] = []
    for src in sorted(GT_SOURCE.glob("*.pdf")):
        sy, _sw1, sw2 = parse_biweekly_label(src.stem)
        all_sources.append((paho_saturday(sy, sw2), src.stem, src))
    all_sources.sort()

    for y, w1, w2, sat in iter_biweekly_issues(args.instance_start, args.instance_end):
        label = biweekly_label(y, w1, w2)
        out_dir = INSTANCES / label
        if not out_dir.exists():
            print(f"[skip] {label}: instance dir missing", flush=True); continue
        visible = [
            {"label": s_label, "path": f"../../gt_source/{s_path.name}",
             "week_ending": s_sat.isoformat()}
            for (s_sat, s_label, s_path) in all_sources
            if s_sat < sat
        ]
        manifest = {
            "instance": label,
            "query_week_ending": sat.isoformat(),
            "visible": visible,
            "count": len(visible),
        }
        (out_dir / "visible_reports.json").write_text(json.dumps(manifest, indent=2))
        print(f"[ok]  {label}: {len(visible)} visible reports", flush=True)


if __name__ == "__main__":
    main()
