"""Render one instance's question from its task's question_template.md.

The template belongs to the task contract (`evbench/tasks/...`). The values
for its `{{placeholders}}` are per-instance facts — which month the data
covers, which month it was released — that only the maintainer knows, so it
writes them to `instances/<period>/instance.json` when it creates the
instance:

    {"period": "2024-05", "template_vars": {"period_label": "2024-05", ...}}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .tasks import task_dir

INSTANCE_FILE = "instance.json"
_PLACEHOLDER = re.compile(r"{{(\w+)}}")


def read_instance(scenario_dir: Path, period: str) -> dict:
    p = scenario_dir / "instances" / period / INSTANCE_FILE
    return json.loads(p.read_text()) if p.exists() else {}


def render_template(template: str, values: dict, where: str = "") -> str:
    missing = sorted(set(_PLACEHOLDER.findall(template)) - set(values))
    if missing:
        raise KeyError(f"{where}: no value for template placeholder(s) {missing}")
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), template)


def render_question(scenario_dir: Path, period: str) -> str:
    """The canonical question text for (scenario, period), before rephrasing.

    Data trees published before instance.json existed carry a pre-rendered
    question.md instead; that is used when instance.json is absent.
    """
    meta = read_instance(scenario_dir, period)
    if not meta:
        legacy = scenario_dir / "instances" / period / "question.md"
        return legacy.read_text() if legacy.exists() else ""
    template = (task_dir(scenario_dir) / "question_template.md").read_text()
    return render_template(template, meta.get("template_vars") or {},
                           where=f"{scenario_dir.name}/{period}")
