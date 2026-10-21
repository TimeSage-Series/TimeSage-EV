"""Render per-instance question.md from environment/question_template.md.

Placeholders substituted:
    {{period}}            e.g. "2024-06"
    {{month_long}}        e.g. "June 2024"
    {{ncei_url}}          e.g. "https://www.ncei.noaa.gov/news/global-climate-202406"

Also copies `answer_schema.json` into each instance directory for runtime
self-containment.

Usage:
    python3 scripts/rephrase_question.py --instance-start 2024-05 \
                                          --instance-end   2026-04
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    ENV, INSTANCES, iter_periods, period_to_yyyymm,
    month_name_long, NCEI_URL_PATTERN,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instance-start", required=True)
    ap.add_argument("--instance-end",   required=True)
    args = ap.parse_args()

    template = (ENV / "question_template.md").read_text()
    schema   = (ENV / "answer_schema.json").read_text()

    n = 0
    for inst in iter_periods(args.instance_start, args.instance_end):
        out_dir = INSTANCES / inst
        if not out_dir.exists():
            print(f"[skip] {inst}: instance dir missing", flush=True)
            continue
        long_name = month_name_long(inst)
        url = NCEI_URL_PATTERN.format(period=period_to_yyyymm(inst))
        rendered = (
            template
            .replace("{{period}}", inst)
            .replace("{{month_long}}", long_name)
            .replace("{{ncei_url}}", url)
        )
        (out_dir / "question.md").write_text(rendered)
        (out_dir / "answer_schema.json").write_text(schema)
        n += 1
        print(f"[ok]  {inst}: {long_name}", flush=True)
    print(f"\n[done] rendered {n} questions", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
