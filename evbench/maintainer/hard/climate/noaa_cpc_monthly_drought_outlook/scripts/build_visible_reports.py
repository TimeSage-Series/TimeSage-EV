"""Build per-instance visible_reports.json — manifest of past MDO issues
visible at query time.

For instance M, the agent can see every MDO issue whose release date is
STRICTLY BEFORE the release date of M. The agent never has direct
access to the M-month outlook (only the time-series snapshot up through
the M release date).

This matches the FQ-08 contract used by the WHO cholera Hard sibling:
the instance dir holds only a manifest, not copies. Eval harness stages
the listed files into /root/gt_source/ at runtime from
scenario-level gt_source/.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (   # noqa: E402
    GT_SOURCE, INSTANCES, iter_months, month_label, release_date_for,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    # Index every gt_source HTML by its release date.
    all_sources: list[tuple[dt.date, str, Path]] = []
    for src in sorted(GT_SOURCE.glob("*.html")):
        try:
            y, m = src.stem.split("-")
            y, m = int(y), int(m)
        except ValueError:
            continue
        rd = release_date_for(y, m)
        all_sources.append((rd, src.stem, src))
    all_sources.sort()

    for y, m in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        out_dir = INSTANCES / label
        if not out_dir.exists():
            print(f"[skip] {label}: instance dir missing", flush=True)
            continue
        this_rd = release_date_for(y, m)
        visible = [
            {
                "label": s_label,
                "path":  f"../../gt_source/{s_path.name}",
                "release_date": s_rd.isoformat(),
            }
            for (s_rd, s_label, s_path) in all_sources
            if s_rd < this_rd
        ]
        manifest = {
            "instance":               label,
            "query_release_date":     this_rd.isoformat(),
            "visible":                visible,
            "count":                  len(visible),
            "note": (
                "Each entry is an MDO narrative HTML visible to the "
                "agent at query time. The eval harness stages these "
                "files into /root/gt_source/<label>.html. The current "
                "month's MDO is intentionally NOT in this list — that's "
                "what the agent must reproduce."
            ),
        }
        (out_dir / "visible_reports.json").write_text(json.dumps(manifest, indent=2))
        print(f"[ok]  {label}: {len(visible)} visible reports", flush=True)


if __name__ == "__main__":
    main()
