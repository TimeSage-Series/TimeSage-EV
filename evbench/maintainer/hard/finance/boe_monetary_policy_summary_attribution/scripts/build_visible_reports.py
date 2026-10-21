"""Build per-instance ``visible_reports.json`` — manifest of past BoE MPC
Monetary Policy Summary PDFs available at the query meeting date.

Same pattern as the WHO cholera Hard scenario: the instance directory
holds only the manifest, not copies of past PDFs. The manifest points
back to the scenario-level ``gt_source/`` via a relative path. The eval
harness is responsible for staging the listed files into
``/root/gt_source/`` at runtime.

A summary PDF for meeting M' is considered 'visible' at instance M if
M' < M (strictly earlier meeting date). The agent never sees the
current-meeting PDF directly — only the cumulative ``timeseries.csv``
row and the prior meetings' PDFs.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE, INSTANCES, iter_meetings, parse_label  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    all_sources: list[tuple] = []
    for src in sorted(GT_SOURCE.glob("*.pdf")):
        all_sources.append((parse_label(src.stem), src.stem, src))
    all_sources.sort()

    for label, d in iter_meetings(args.instance_start, args.instance_end):
        out_dir = INSTANCES / label
        if not out_dir.exists():
            print(f"[skip] {label}: instance dir missing", flush=True); continue
        visible = [
            {
                "label":        s_label,
                "path":         f"../../gt_source/{s_path.name}",
                "meeting_date": s_date.isoformat(),
            }
            for (s_date, s_label, s_path) in all_sources
            if s_date < d
        ]
        manifest = {
            "instance":          label,
            "query_meeting_date": d.isoformat(),
            "visible":           visible,
            "count":             len(visible),
        }
        (out_dir / "visible_reports.json").write_text(json.dumps(manifest, indent=2))
        print(f"[ok]  {label}: {len(visible)} visible reports", flush=True)


if __name__ == "__main__":
    main()
