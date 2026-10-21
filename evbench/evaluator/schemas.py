"""Data schemas for the eval suite.

"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ---------- Scenario-side -------------------------------------------------


class Keypoint(BaseModel):
    id: str
    description: str
    answer_field: Optional[str] = None        # GT field this kp anchors to; None = report-only
    question_tag: str                         # A1..F4 question-type taxonomy
    verification_question: str
    answer_type: Literal["enum", "numeric", "number", "string_set", "list",
                         "boolean", "string", "free_text"]
    enum_options: Optional[list[str]] = None
    tolerance_abs: Optional[float] = None
    tolerance_rel: Optional[float] = None


class FaithfulnessSources(BaseModel):
    tier1_keypoints: bool = True
    tier2_context: list[dict[str, Any]] = Field(default_factory=list)
    tier3_external: bool = True


class QualityRubric(BaseModel):
    genre: str
    required_signals: list[str] = Field(default_factory=list)
    forbidden_signals: list[str] = Field(default_factory=list)
    exemplar: Optional[str] = None


class ScenarioDef(BaseModel):
    scenario_id: str
    tier: Literal["easy", "middle", "hard"]
    domain: str
    question_tags: list[str]
    answer_schema: dict[str, Any]              # raw JSON-Schema dict
    keypoints: list[Keypoint]
    faithfulness_sources: FaithfulnessSources
    quality_rubric: QualityRubric
    pass_threshold: float = 80.0           # 0-100 scale, like aggregate
    keypoints_auto_derived: bool = False       # True if keypoints.yaml was missing


# ---------- Agent-side -----------------------------------------------------


class AgentMeta(BaseModel):
    model: Optional[str] = None
    framework: Optional[str] = None
    timestamp: Optional[str] = None


class RunRecord(BaseModel):
    run_id: str
    scenario_id: str
    tier: Literal["easy", "middle", "hard"]
    period: str
    agent_meta: AgentMeta = Field(default_factory=AgentMeta)
    structured_answer: dict[str, Any]
    # The report is the schema's `report` field, so run records keep it only
    # in structured_answer; a top-level copy is for agents that return it
    # outside the answer.
    report: str = ""

    @model_validator(mode="after")
    def _report_from_answer(self) -> "RunRecord":
        if not self.report and isinstance(self.structured_answer.get("report"), str):
            self.report = self.structured_answer["report"]
        return self


# ---------- Score-side -----------------------------------------------------


class AxisScore(BaseModel):
    name: Literal["keypoint_accuracy", "keypoint_coverage",
                  "report_faithfulness", "report_quality"]
    value: Optional[float] = None              # None = judge_unavailable or skipped
    status: Literal["scored", "skipped", "judge_unavailable", "structural_only"] = "scored"
    detail: dict[str, Any] = Field(default_factory=dict)


class ScoreRecord(BaseModel):
    run_id: str
    scenario_id: str
    tier: Literal["easy", "middle", "hard"]
    period: str
    question_types: list[str]                  # ["A","B",...] derived from question_tags
    scores: dict[str, AxisScore]               # keyed by axis name (4 axes)
    # Per-question-type slice of Accuracy only — Coverage/Faithfulness/Quality are
    # instance-level scalars and have no qtype attribution.
    accuracy_by_qtype: dict[str, float] = Field(default_factory=dict)
    aggregate: Optional[float] = None
    pass_threshold: float = 80.0           # 0-100 scale, like aggregate
    passed: bool = False
    judge: dict[str, Any] = Field(default_factory=dict)   # Judge.describe()
    judge_cost_usd: float = 0.0
    wall_time_ms: int = 0
    failure_mode: Optional[str] = None
    structural_only: bool = False              # True when structured_answer was malformed


class AccuracyCell(BaseModel):
    """One cell of the tier × qtype Accuracy matrix."""
    accuracy: Optional[float] = None
    n: int = 0
    n_clusters: int = 0
    stddev: Optional[float] = None
    ci: Optional[list[float]] = None             # [lo, hi], cluster-bootstrap


class ReportAxesCell(BaseModel):
    """Per-tier aggregate of the three report-level axes."""
    coverage: Optional[float] = None
    faithfulness: Optional[float] = None
    quality: Optional[float] = None
    n: int = 0
    n_clusters: int = 0
    stddev: dict[str, float] = Field(default_factory=dict)
    ci: dict[str, list[float]] = Field(default_factory=dict)


class TotalsRow(BaseModel):
    """Suite-wide totals across all records."""
    accuracy: Optional[float] = None
    coverage: Optional[float] = None
    faithfulness: Optional[float] = None
    quality: Optional[float] = None
    n: int = 0
    n_clusters: int = 0                                    # distinct scenario_ids
    stddev: dict[str, float] = Field(default_factory=dict)
    # Cluster bootstrap CI (resample at scenario_id level): {metric: [lo, hi]}.
    ci: dict[str, list[float]] = Field(default_factory=dict)
    ci_method: Optional[str] = None                        # e.g. "cluster_bootstrap_bca_95"


class AggregationRecord(BaseModel):
    run_summary_id: str
    n_scenarios: int
    n_runs: int
    # tier × qtype, only Accuracy lives here
    accuracy_matrix: dict[str, dict[str, Optional[AccuracyCell]]]
    # tier → (coverage, faithfulness, quality)
    report_axes: dict[str, Optional[ReportAxesCell]]
    totals: TotalsRow
    total_judge_cost_usd: float = 0.0
    # CI provenance — None when aggregate() was called with with_ci=False.
    ci_settings: Optional[dict[str, Any]] = None
