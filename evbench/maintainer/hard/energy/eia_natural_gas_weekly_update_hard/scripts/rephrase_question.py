"""Per-instance question.md."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import INSTANCES, ENV  # noqa


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-dates", required=True)
    args = ap.parse_args()
    tpl = (ENV / "question_template.md").read_text()
    schema = (ENV / "answer_schema.json").read_text()
    targets = [d.strip() for d in args.instance_dates.split(",") if d.strip()]
    for label in targets:
        out_dir = INSTANCES / label
        if not out_dir.exists(): continue
        manifest = out_dir / "visible_reports.json"
        n_prior = 0
        if manifest.exists():
            n_prior = json.loads(manifest.read_text()).get("count", 0)
        rendered = (tpl
                    .replace("{{PUBLICATION_THURSDAY}}", label)
                    .replace("{{N_PRIOR_REPORTS}}", str(n_prior)))
        (out_dir / "question.md").write_text(rendered)
        (out_dir / "answer_schema.json").write_text(schema)
        print(f"[ok]   {label}: n_prior={n_prior}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
