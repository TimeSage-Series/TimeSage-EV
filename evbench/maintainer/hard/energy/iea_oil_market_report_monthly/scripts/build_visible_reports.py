"""Build per-instance visible_reports.json — manifest of prior OMR PDFs.

An OMR PDF is 'visible' at instance L if its publication_date_approx is
STRICTLY BEFORE L's publication_date_approx. The current-issue PDF is
intentionally NOT staged for the agent — the agent only sees the typed row
in timeseries.csv for the current issue. This enforces V7 information
isolation: the Hard task is causal reasoning over the cumulative trajectory
plus visible history, not extraction from the current PDF.

The manifest's `path` fields are RELATIVE to instances/<label>/, so an eval
harness staging routine should resolve them against the scenario root before
copying into /root/gt_source/ on the agent container.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE, INSTANCES, iter_months, month_label  # noqa: E402

LANDING_PATH = Path(__file__).parent / "landing_urls.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    data = json.loads(LANDING_PATH.read_text())
    issues = data["issues"]

    # Index every PDF on disk by label, with its approximate publication date.
    available: list[tuple[str, str, Path]] = []
    for p in sorted(GT_SOURCE.glob("*.pdf")):
        label = p.stem
        pub = issues.get(label, {}).get("published_approx") or label + "-01"
        available.append((label, pub, p))
    available.sort(key=lambda t: t[1])

    for d in iter_months(args.instance_start, args.instance_end):
        label = month_label(d)
        out_dir = INSTANCES / label
        if not out_dir.exists():
            print(f"[skip] {label}: instance dir missing", flush=True); continue
        cur_pub = issues.get(label, {}).get("published_approx") or label + "-01"
        visible = [
            {"label": s_label, "path": f"../../gt_source/{s_path.name}",
             "publication_date_approx": s_pub}
            for (s_label, s_pub, s_path) in available
            if s_pub < cur_pub
        ]
        manifest = {
            "instance":                       label,
            "query_publication_date_approx":  cur_pub,
            "visible":                        visible,
            "count":                          len(visible),
            "note": (
                "These prior OMR Highlights PDFs are visible to the agent at "
                "this instance. The CURRENT issue's PDF is intentionally NOT "
                "staged — only its extracted typed row in timeseries.csv. The "
                "eval harness must copy every listed file into /root/gt_source/ "
                "before running the agent. Paths above are relative to "
                "instances/<label>/."
            ),
        }
        (out_dir / "visible_reports.json").write_text(json.dumps(manifest, indent=2))
        print(f"[ok]   {label}: {len(visible)} visible reports", flush=True)


if __name__ == "__main__":
    main()
