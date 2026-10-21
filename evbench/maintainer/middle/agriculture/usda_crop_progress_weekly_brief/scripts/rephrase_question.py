"""Render per-instance question.md + copy answer_schema.json."""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ENV, INSTANCES, parse_label  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    template = (ENV / "question_template.md").read_text()
    schema   = ENV / "answer_schema.json"

    sy, sw = parse_label(args.instance_start); ey, ew = parse_label(args.instance_end)
    for inst in sorted(INSTANCES.iterdir()):
        label = inst.name
        try: yr, wk = parse_label(label)
        except ValueError: continue
        if (yr, wk) < (sy, sw) or (yr, wk) > (ey, ew): continue
        gt_path = inst / "ground_truth.json"
        we = label
        if gt_path.exists():
            we = json.loads(gt_path.read_text()).get("week_ending", label)
        rendered = (template
                    .replace("{{usda_week_label}}", label)
                    .replace("{{week_ending}}", we or label))
        (inst / "question.md").write_text(rendered)
        shutil.copy(schema, inst / "answer_schema.json")
        print(f"[ok]  {label}", flush=True)


if __name__ == "__main__":
    main()
