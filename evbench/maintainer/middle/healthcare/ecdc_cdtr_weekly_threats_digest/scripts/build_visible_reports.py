"""Build per-instance visible_reports.json — manifest of past CDTR PDFs.

Same pattern as scenario 1: instance dir holds only the manifest, not
copies. The manifest points back to scenario-level gt_source/ via relative
path. Eval harness stages the listed files into /root/gt_source/ at runtime.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE, INSTANCES, iter_iso_weeks, iso_week_label, iso_saturday  # noqa


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    all_sources: list[tuple[dt.date, str, Path]] = []
    for src in sorted(GT_SOURCE.glob("*.pdf")):
        sy, sw = src.stem.split("-W"); sy, sw = int(sy), int(sw)
        all_sources.append((iso_saturday(sy, sw), src.stem, src))
    all_sources.sort()

    for y, w, sat in iter_iso_weeks(args.instance_start, args.instance_end):
        label = iso_week_label(y, w)
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
