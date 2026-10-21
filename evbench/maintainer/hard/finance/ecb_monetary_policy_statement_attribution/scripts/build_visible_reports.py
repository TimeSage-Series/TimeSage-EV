"""Build per-instance visible_reports.json — manifest of past ECB statements.

Same pattern as the WHO cholera Hard template: instance dir holds only the
manifest, not copies. The manifest points back to scenario-level gt_source/
via relative path. Eval harness stages the listed files into /root/gt_source/
at runtime.

A Combined-statement PDF for meeting M is considered 'visible' at instance
M' if its publication date is STRICTLY BEFORE the publication date of M'.
The agent never sees the current meeting's Combined-statement PDF directly —
only the extracted typed fields in /root/timeseries.csv and the prior PDFs.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    GT_SOURCE, INSTANCES,
    label_from_date, parse_label, iter_meetings,
)  # noqa

LANDING_PATH = Path(__file__).parent / "landing_urls.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    landing_data = json.loads(LANDING_PATH.read_text())
    meetings_all = landing_data["meeting_dates"]

    all_sources: list[tuple[dt.date, str, Path]] = []
    for src in sorted(GT_SOURCE.glob("*.pdf")):
        d = parse_label(src.stem)
        all_sources.append((d, src.stem, src))
    all_sources.sort()

    for d in iter_meetings(meetings_all, args.instance_start, args.instance_end):
        label = label_from_date(d)
        out_dir = INSTANCES / label
        if not out_dir.exists():
            print(f"[skip] {label}: instance dir missing", flush=True)
            continue
        visible = [
            {"label": s_label,
             "path": f"../../gt_source/{s_path.name}",
             "publication_date": s_d.isoformat()}
            for (s_d, s_label, s_path) in all_sources
            if s_d < d
        ]
        manifest = {
            "instance":            label,
            "query_publication_date": d.isoformat(),
            "visible":             visible,
            "count":               len(visible),
        }
        (out_dir / "visible_reports.json").write_text(json.dumps(manifest, indent=2))
        print(f"[ok]  {label}: {len(visible)} visible past statements", flush=True)


if __name__ == "__main__":
    main()
