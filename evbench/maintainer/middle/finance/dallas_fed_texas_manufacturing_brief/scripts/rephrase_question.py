"""Per-instance question.md."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import INSTANCES, ENV, iter_months, month_label, month_label_long  # noqa


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end",   required=True)
    args = ap.parse_args()
    tpl = (ENV / "question_template.md").read_text()
    schema = (ENV / "answer_schema.json").read_text()
    for y, m in iter_months(args.start, args.end):
        label = month_label(y, m)
        out_dir = INSTANCES / label
        if not out_dir.exists(): continue
        manifest_path = out_dir / "visible_reports.json"
        n_prior = 0
        if manifest_path.exists():
            n_prior = json.loads(manifest_path.read_text()).get("count", 0)
        q = (tpl.replace("{{DATA_MONTH}}", label)
                .replace("{{DATA_MONTH_LONG}}", month_label_long(y, m))
                .replace("{{N_PRIOR_REPORTS}}", str(n_prior)))
        (out_dir / "question.md").write_text(q)
        (out_dir / "answer_schema.json").write_text(schema)
        print(f"[ok]   {label}: n_prior={n_prior}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
