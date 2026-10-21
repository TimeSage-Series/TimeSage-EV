"""Write instances/<period>/instance.json.

An instance's question is rendered at run time by evbench/engine/question.py
from the task's question_template.md. The placeholder values are facts about
the instance that only the scenario's own scripts know — the data month a
release covers, the ISO week label, the last observation date — so each
scenario's scripts/template_vars.py computes them and hands them to
write_instance().
"""
from __future__ import annotations

import json
from pathlib import Path


def write_instance(inst_dir: Path, template_vars: dict) -> Path:
    p = inst_dir / "instance.json"
    p.write_text(json.dumps({"period": inst_dir.name,
                             "template_vars": template_vars}, indent=2) + "\n",
                 encoding="utf-8")
    return p
