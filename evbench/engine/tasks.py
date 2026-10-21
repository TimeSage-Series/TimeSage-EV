"""Load a task contract into a ScenarioDef.

A task contract is everything that defines a scenario's task independently of
any one period: session_brief.md, question_template.md, answer_schema.json,
keypoints.yaml, eval_rubric.yaml, scoring.yaml, question_tags.yaml. It lives
in `evbench/tasks/<tier>/<domain>/<id>/`. Auto-derives keypoints + rubric
when their files are missing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from evbench.evaluator.schemas import (
    FaithfulnessSources,
    Keypoint,
    QualityRubric,
    ScenarioDef,
)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


TIER_DEFAULT_RUBRIC = {
    "easy":   ("1–2 sentence plain factual statement of the current state.",
               ["Names the current period explicitly.",
                "States the answer using a controlled-vocab label."],
               ["Speculates about future periods.",
                "Adds editorial commentary."]),
    "middle": ("2–4 sentence summary covering the dominant signal + at least one comparison.",
               ["Names the current period.",
                "States the dominant value with units.",
                "Includes one comparison (vs prior period, baseline, or peer)."],
               ["Predicts the next period.",
                "Attributes causes beyond what the data supports."]),
    "hard":   ("3–6 sentence analytical brief covering the signal, drivers, and outlook.",
               ["Names the current period.",
                "States the headline metric with magnitude.",
                "Cites at least two analytical drivers.",
                "Articulates a forward-looking outlook."],
               ["Fabricates verbatim quotes from the current-period report.",
                "Cites the current-period report as a source."]),
}


def _auto_derive_keypoints(scenario_id: str,
                           tier: str,
                           answer_schema: dict[str, Any],
                           question_tags_doc: dict[str, Any]) -> list[Keypoint]:
    """Fallback when environment/keypoints.yaml is missing.

    Maps every required schema field to a keypoint, using the per-field tag
    declared in environment/question_tags.yaml to pick a verification
    question template.
    """
    qa_fields = {f["field"]: f for f in question_tags_doc.get("qa_fields") or []}
    keypoints: list[Keypoint] = []
    required = answer_schema.get("required") or []
    properties = answer_schema.get("properties") or {}
    for field in required:
        spec = properties.get(field) or {}
        qa = qa_fields.get(field, {})
        tag = qa.get("tag") or "A1"
        if tag == "metadata":
            continue  # don't keypoint pure anchor fields
        # Determine answer_type from schema
        t = spec.get("type") or "string"
        if "enum" in spec:
            answer_type = "enum"
            enum_options = list(spec["enum"])
        elif t == "number" or t == "integer":
            answer_type = "numeric"
            enum_options = None
        elif t == "array":
            answer_type = "string_set"
            enum_options = None
        elif t == "boolean":
            answer_type = "boolean"
            enum_options = None
        else:
            answer_type = "string"
            enum_options = None
        kp = Keypoint(
            id=f"kp_{field}",
            description=spec.get("description") or f"Value of {field}",
            answer_field=field,
            question_tag=tag,
            verification_question=f"What is the {field} for this period?",
            answer_type=answer_type,
            enum_options=enum_options,
            tolerance_abs=qa.get("tolerance_abs") or qa.get("tolerance"),
            tolerance_rel=qa.get("tolerance_rel"),
        )
        keypoints.append(kp)
    return keypoints


def _auto_derive_rubric(tier: str) -> QualityRubric:
    genre, req, forb = TIER_DEFAULT_RUBRIC.get(tier, TIER_DEFAULT_RUBRIC["middle"])
    return QualityRubric(genre=genre, required_signals=req, forbidden_signals=forb)


#: Hand-authored task contracts, one directory per scenario.
TASKS_ROOT = Path(__file__).resolve().parents[1] / "tasks"


def task_dir(scenario_dir: Path) -> Path:
    """The task contract directory for a scenario.

    `scenario_dir` is a data-tree path (`evbench/scenarios/`, `scenarios_wkspace/`,
    or $TIMESAGE_DATA_ROOT) holding instances/ and gt_source/; the contract is
    at the same `<tier>/<domain>/<id>` under TASKS_ROOT. A local
    `environment/` in the data tree still wins, for old checkouts.
    """
    local = scenario_dir / "environment"
    if local.is_dir():
        return local
    return TASKS_ROOT.joinpath(*scenario_dir.resolve().parts[-3:])


def read_session_brief(scenario_dir: Path) -> str:
    p = task_dir(scenario_dir) / "session_brief.md"
    return p.read_text() if p.exists() else ""


def load_scenario(scenario_dir: Path) -> ScenarioDef:
    """Load a ScenarioDef from a path like `evbench/scenarios/easy/climate/noaa_cpc_ao_monthly_phase`."""
    scen_yaml = _read_yaml(scenario_dir / "scenario.yaml")
    env_dir = task_dir(scenario_dir)
    answer_schema = _read_json(env_dir / "answer_schema.json")
    question_tags_doc = _read_yaml(env_dir / "question_tags.yaml")
    keypoints_doc = _read_yaml(env_dir / "keypoints.yaml")
    rubric_doc = _read_yaml(env_dir / "eval_rubric.yaml")

    scenario_id = scen_yaml.get("scenario_id") or scenario_dir.name
    tier = scen_yaml.get("tier") or scenario_dir.parts[-3]
    domain = scen_yaml.get("domain") or scenario_dir.parts[-2]
    question_tags = list(scen_yaml.get("question_tags") or [])

    if keypoints_doc.get("keypoints"):
        kps = [Keypoint(**kp) for kp in keypoints_doc["keypoints"]]
        auto = False
    else:
        kps = _auto_derive_keypoints(scenario_id, tier, answer_schema, question_tags_doc)
        auto = True

    fs = keypoints_doc.get("faithfulness_sources") or {}
    fs_obj = FaithfulnessSources(
        tier1_keypoints=fs.get("tier1_keypoints", True),
        tier2_context=list(fs.get("tier2_context") or []),
        tier3_external=fs.get("tier3_external", True),
    )

    if rubric_doc.get("quality_rubric"):
        rubric = QualityRubric(**rubric_doc["quality_rubric"])
    else:
        rubric = _auto_derive_rubric(tier)

    scoring_yaml = _read_yaml(env_dir / "scoring.yaml")
    # Canonical scale is 0-100. Legacy scoring.yaml files use 0-1 — auto-promote
    # any threshold ≤ 1 by multiplying by 100 so old configs keep working.
    # Two conventions in the wild:
    #   pass_threshold: 0.7            (top-level, ~5 scenarios)
    #   aggregation:
    #     pass_threshold: 0.7          (nested under aggregation, ~53 scenarios)
    # Prefer top-level, fall back to nested.
    raw_threshold = scoring_yaml.get("pass_threshold")
    if raw_threshold is None:
        agg_block = scoring_yaml.get("aggregation") or {}
        if isinstance(agg_block, dict):
            raw_threshold = agg_block.get("pass_threshold")
    if raw_threshold is None:
        pass_threshold = 80.0
    else:
        pt = float(raw_threshold)
        pass_threshold = pt * 100 if pt <= 1.0 else pt

    return ScenarioDef(
        scenario_id=scenario_id,
        tier=tier,
        domain=domain,
        question_tags=question_tags,
        answer_schema=answer_schema,
        keypoints=kps,
        faithfulness_sources=fs_obj,
        quality_rubric=rubric,
        pass_threshold=pass_threshold,
        keypoints_auto_derived=auto,
    )
