"""Unit tests for the 4 scorers + aggregator.

Run:  python3 -m unittest evbench.evaluator.tests.test_scorers
or:   python3 -m unittest discover -s evbench/evaluator/tests -t . -v
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import sys
HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3]))  # repo root

from evbench.evaluator.aggregator import aggregate, cluster_bootstrap_ci   # noqa: E402
from evbench.evaluator.judge import Judge                                  # noqa: E402
from evbench.engine.tasks import load_scenario                             # noqa: E402
from evbench.evaluator.schemas import RunRecord, ScoreRecord, AxisScore    # noqa: E402
from evbench.evaluator.scorers import (                                    # noqa: E402
    accuracy, coverage, faithfulness, quality,
)


REPO = HERE.parents[3]


def _scen_easy():
    return load_scenario(REPO / "evbench/scenarios/easy/climate/noaa_cpc_ao_monthly_phase")


def _run_easy_correct():
    p = REPO / "evbench/evaluator/fixtures/easy__noaa_cpc_ao/agent_output__2024-05.json"
    return RunRecord(**json.loads(p.read_text()))


def _run_easy_wrong():
    """Same shape, wrong answer + thin report."""
    r = _run_easy_correct().model_copy(deep=True)
    r.structured_answer["ao_phase"] = "Positive"  # GT is Neutral
    r.report = "AO is Positive."                   # missing month, missing index value
    return r


class KeypointAccuracyTests(unittest.TestCase):
    def test_correct_run_scores_1(self):
        judge = Judge(mock=True)
        run = _run_easy_correct()
        gt = {"ao_phase": "Neutral", "as_of_month": "2024-05"}
        s = accuracy.score(run, _scen_easy(), gt, judge)
        self.assertEqual(s.status, "scored")
        self.assertGreaterEqual(s.value, 70)

    def test_wrong_run_scores_below_threshold(self):
        judge = Judge(mock=True)
        run = _run_easy_wrong()
        gt = {"ao_phase": "Neutral", "as_of_month": "2024-05"}
        s = accuracy.score(run, _scen_easy(), gt, judge)
        # Main keypoint is wrong → score drops below 70
        self.assertLess(s.value, 70)


class KeypointCoverageTests(unittest.TestCase):
    def test_full_report_gets_yes(self):
        judge = Judge(mock=True, mock_responses={"convey": "YES"})
        run = _run_easy_correct()
        gt = {"ao_phase": "Neutral", "as_of_month": "2024-05"}
        s = coverage.score(run, _scen_easy(), gt, judge)
        self.assertEqual(s.status, "scored")
        # All KPs hit
        self.assertEqual(s.value, 100)

    def test_thin_report_partial(self):
        # Mock judge returns NO for the threshold-rationale KP
        judge = Judge(mock=True, mock_responses={
            "threshold": "NO",        # the kp_threshold_rationale prompt contains 'threshold'
            "convey": "YES",
        })
        run = _run_easy_wrong()
        gt = {"ao_phase": "Neutral", "as_of_month": "2024-05"}
        s = coverage.score(run, _scen_easy(), gt, judge)
        self.assertLess(s.value, 100)


class FaithfulnessTests(unittest.TestCase):
    def test_supported_facts_score_high(self):
        # Default mock returns tier1_supported for every fact
        judge = Judge(mock=True)
        run = _run_easy_correct()
        gt = {"ao_phase": "Neutral", "as_of_month": "2024-05"}
        s = faithfulness.score(run, _scen_easy(), gt, judge, context_excerpts=["ao_value: -0.05"])
        self.assertEqual(s.status, "scored")
        self.assertGreaterEqual(s.value, 80)

    def test_contradiction_drops_score(self):
        judge = Judge(mock=True, mock_responses={
            "Verify a single atomic":  json.dumps({"verdict": "contradicts_keypoint"}),
        })
        run = _run_easy_correct()
        gt = {"ao_phase": "Neutral", "as_of_month": "2024-05"}
        s = faithfulness.score(run, _scen_easy(), gt, judge, context_excerpts=[])
        self.assertEqual(s.value, 0.0)


class QualityTests(unittest.TestCase):
    def test_clean_report_high(self):
        judge = Judge(mock=True, mock_responses={"scoring a report's WRITING": json.dumps({
            "required_hits": ["Names the current month explicitly (e.g. 'May 2024').",
                              "States the AO phase using one of the controlled enum labels (Positive / Negative / Neutral)."],
            "required_partial": [],
            "required_misses": [],
            "forbidden_violations": [],
            "rationale": "Genre-conforming.",
        })})
        run = _run_easy_correct()
        gt = {"ao_phase": "Neutral", "as_of_month": "2024-05"}
        s = quality.score(run, _scen_easy(), gt, judge)
        self.assertEqual(s.value, 100)

    def test_forbidden_violation_drops_score(self):
        judge = Judge(mock=True, mock_responses={"scoring a report's WRITING": json.dumps({
            "required_hits": ["States the AO phase using one of the controlled enum labels (Positive / Negative / Neutral)."],
            "required_partial": [],
            "required_misses": ["Names the current month explicitly (e.g. 'May 2024')."],
            "forbidden_violations": ["Speculates about next month or future periods."],
            "rationale": "Missing month + speculates.",
        })})
        run = _run_easy_wrong()
        gt = {"ao_phase": "Neutral", "as_of_month": "2024-05"}
        s = quality.score(run, _scen_easy(), gt, judge)
        self.assertLess(s.value, 60)


class AggregatorTests(unittest.TestCase):
    def _rec(self, tier, accuracy_by_qtype, kA_overall, kC, F, Q, scenario_id="x", period="p"):
        """Build a synthetic ScoreRecord.

        accuracy_by_qtype: e.g. {"A": 100, "B": 50} — drives the Accuracy matrix.
        kA_overall: instance-level Accuracy axis value (used in Totals only).
        kC / F / Q: instance-level Coverage / Faithfulness / Quality.
        """
        scores = {
            "keypoint_accuracy":   AxisScore(name="keypoint_accuracy",   value=kA_overall, status="scored"),
            "keypoint_coverage":   AxisScore(name="keypoint_coverage",   value=kC, status="scored"),
            "report_faithfulness": AxisScore(name="report_faithfulness", value=F,  status="scored"),
            "report_quality":      AxisScore(name="report_quality",      value=Q,  status="scored"),
        }
        avg = (kA_overall + kC + F + Q) / 4
        return ScoreRecord(
            run_id=f"{scenario_id}/{period}", scenario_id=scenario_id, tier=tier, period=period,
            question_types=sorted(accuracy_by_qtype.keys()),
            scores=scores,
            accuracy_by_qtype=accuracy_by_qtype,
            aggregate=avg, passed=avg >= 70,
        )

    def test_accuracy_matrix_shape(self):
        recs = [
            self._rec("easy",   {"A": 100},          100, 100, 100, 100),
            self._rec("easy",   {"A":  50},           50,  50,  50,  50),
            self._rec("middle", {"A": 80, "B": 70},   75,  70,  80,  70),
            self._rec("hard",   {"E": 90, "F": 80},   85,  80,  90,  80),
        ]
        agg = aggregate(recs)
        # 3 tiers x 6 qtypes = 18 cells
        self.assertEqual(set(agg.accuracy_matrix.keys()), {"easy", "middle", "hard"})
        for tier in agg.accuracy_matrix.values():
            self.assertEqual(set(tier.keys()), {"A","B","C","D","E","F"})
        # easy.A: mean of 100 and 50 -> 75
        self.assertEqual(agg.accuracy_matrix["easy"]["A"].accuracy, 75)
        # easy.B is empty (no records contributed)
        self.assertIsNone(agg.accuracy_matrix["easy"]["B"])
        # middle.A and middle.B both populated from the same record
        self.assertEqual(agg.accuracy_matrix["middle"]["A"].accuracy, 80)
        self.assertEqual(agg.accuracy_matrix["middle"]["B"].accuracy, 70)

    def test_report_axes_per_tier(self):
        recs = [
            self._rec("easy",   {"A": 100}, 100,  80,  90, 70),
            self._rec("easy",   {"A":  50},  50,  60,  70, 50),
            self._rec("middle", {"A":  90},  90,  85,  95, 80),
        ]
        agg = aggregate(recs)
        # easy averaged across 2 records
        self.assertEqual(agg.report_axes["easy"].coverage,     70)   # (80+60)/2
        self.assertEqual(agg.report_axes["easy"].faithfulness, 80)   # (90+70)/2
        self.assertEqual(agg.report_axes["easy"].quality,      60)   # (70+50)/2
        self.assertEqual(agg.report_axes["easy"].n, 2)
        # hard had no records
        self.assertIsNone(agg.report_axes["hard"])
        # totals span everything
        self.assertEqual(agg.totals.n, 3)

    def test_with_ci_false_is_default(self):
        # Hot-path default: no CI computation, ci_settings is None.
        recs = [
            self._rec("easy", {"A": 100}, 100, 80, 90, 70, scenario_id="s1"),
            self._rec("easy", {"A":  60},  60, 60, 70, 50, scenario_id="s2"),
        ]
        agg = aggregate(recs)
        self.assertIsNone(agg.ci_settings)
        self.assertEqual(agg.totals.ci, {})
        self.assertIsNone(agg.totals.ci_method)
        self.assertIsNone(agg.accuracy_matrix["easy"]["A"].ci)
        self.assertEqual(agg.report_axes["easy"].ci, {})

    def test_single_cluster_yields_no_ci(self):
        # All records share scenario_id="x" → n_clusters=1 → CI undefined,
        # but ci_settings is still populated because the caller asked for CI.
        recs = [
            self._rec("easy", {"A": 100}, 100, 80, 90, 70),
            self._rec("easy", {"A":  50},  50, 60, 70, 50),
        ]
        agg = aggregate(recs, with_ci=True, ci_n_resamples=99)
        self.assertEqual(agg.totals.n_clusters, 1)
        self.assertEqual(agg.totals.ci, {})
        self.assertIsNone(agg.totals.ci_method)
        self.assertIsNotNone(agg.ci_settings)
        self.assertIsNone(agg.accuracy_matrix["easy"]["A"].ci)

    def _multi_scenario_recs(self, tier="easy", qtype="A", n_periods=4):
        """Build records spanning 6 scenarios, each with n_periods periods,
        with scenario-level mean spread across the [0,100] range."""
        import random
        rng = random.Random(0)
        scen_means = {"s1": 90, "s2": 80, "s3": 70, "s4": 60, "s5": 50, "s6": 40}
        recs = []
        for sid, mu in scen_means.items():
            for p in range(n_periods):
                v = max(0.0, min(100.0, mu + rng.uniform(-5, 5)))
                recs.append(self._rec(tier, {qtype: v}, v, v, v, v,
                                       scenario_id=sid, period=f"2024-{p:02d}"))
        return recs

    def test_totals_ci_brackets_mean(self):
        recs = self._multi_scenario_recs()
        agg = aggregate(recs, with_ci=True, ci_n_resamples=999, ci_seed=42)
        self.assertEqual(agg.totals.n, 24)
        self.assertEqual(agg.totals.n_clusters, 6)
        for k in ("accuracy", "coverage", "faithfulness", "quality"):
            self.assertIn(k, agg.totals.ci)
            lo, hi = agg.totals.ci[k]
            self.assertLessEqual(lo, getattr(agg.totals, k))
            self.assertGreaterEqual(hi, getattr(agg.totals, k))
            self.assertLess(lo, hi)

    def test_accuracy_cell_ci_brackets_cell_mean(self):
        recs = self._multi_scenario_recs(tier="easy", qtype="A")
        agg = aggregate(recs, with_ci=True, ci_n_resamples=999, ci_seed=0)
        cell = agg.accuracy_matrix["easy"]["A"]
        self.assertIsNotNone(cell)
        self.assertIsNotNone(cell.ci)
        self.assertEqual(cell.n, 24)
        self.assertEqual(cell.n_clusters, 6)
        lo, hi = cell.ci
        self.assertLessEqual(lo, cell.accuracy)
        self.assertGreaterEqual(hi, cell.accuracy)
        # Empty cells (no records contributed) stay None.
        self.assertIsNone(agg.accuracy_matrix["easy"]["B"])
        # hard tier has no records → entire row is None.
        self.assertIsNone(agg.accuracy_matrix["hard"]["A"])

    def test_report_axes_cell_ci_brackets_means(self):
        recs = self._multi_scenario_recs(tier="middle", qtype="B")
        agg = aggregate(recs, with_ci=True, ci_n_resamples=999, ci_seed=0)
        cell = agg.report_axes["middle"]
        self.assertIsNotNone(cell)
        self.assertEqual(cell.n_clusters, 6)
        for k in ("coverage", "faithfulness", "quality"):
            self.assertIn(k, cell.ci)
            lo, hi = cell.ci[k]
            self.assertLessEqual(lo, getattr(cell, k))
            self.assertGreaterEqual(hi, getattr(cell, k))

    def test_ci_settings_provenance(self):
        recs = self._multi_scenario_recs()
        agg = aggregate(recs, with_ci=True,
                        ci_level=0.9, ci_n_resamples=500,
                        ci_method="percentile", ci_seed=7)
        self.assertIsNotNone(agg.ci_settings)
        self.assertEqual(agg.ci_settings["method"], "cluster_bootstrap_percentile_90")
        self.assertEqual(agg.ci_settings["level"], 0.9)
        self.assertEqual(agg.ci_settings["n_resamples"], 500)
        self.assertEqual(agg.ci_settings["seed"], 7)
        self.assertEqual(agg.ci_settings["cluster"], "scenario_id")

    def test_cluster_bootstrap_constant_is_degenerate(self):
        # All values identical → CI collapses to (mean, mean), no crash.
        ci = cluster_bootstrap_ci({"s1": [50.0, 50.0], "s2": [50.0]})
        self.assertEqual(ci, [50.0, 50.0])


if __name__ == "__main__":
    unittest.main()
