"""Per-instance visible_reports.json manifest."""
from __future__ import annotations
import argparse, datetime as dt, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import GT_SOURCE, INSTANCES, iter_months, month_label, last_of_month  # noqa


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end", required=True)
    args = ap.parse_args()

    pdfs = []
    for pdf in sorted(GT_SOURCE.glob("*.pdf")):
        y, m = map(int, pdf.stem.split("-"))
        pdfs.append((last_of_month(y, m), pdf.stem, pdf))

    for y, m, _ in iter_months(args.instance_start, args.instance_end):
        label = month_label(y, m)
        out = INSTANCES / label
        if not out.exists():
            print(f"[skip] {label}", flush=True); continue
        end = last_of_month(y, m)
        visible = [{"label": s_l, "path": f"../../gt_source/{s_p.name}",
                    "period_end": s_e.isoformat()}
                   for (s_e, s_l, s_p) in pdfs if s_e < end]
        (out / "visible_reports.json").write_text(json.dumps({
            "instance": label, "query_period_end": end.isoformat(),
            "visible": visible, "count": len(visible),
        }, indent=2))
        print(f"[ok]  {label}: {len(visible)} visible", flush=True)


if __name__ == "__main__":
    main()
