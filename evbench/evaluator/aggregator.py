"""Aggregation layer.

Two-axis design:

  - Accuracy is per-keypoint, sliced by question type → 3 × 6 tier × qtype matrix.
  - Coverage / Faithfulness / Quality are instance-level scalars → 3 × 3 per-tier
    table (no qtype attribution to avoid double-counting).

All scores live on a 0-100 scale.

**Cluster bootstrap CI.** Every cell (matrix cells, per-tier report axes, and
totals) can carry a cluster-bootstrap CI that resamples scenarios — not
instances — because consecutive periods of the same scenario are heavily
autocorrelated. The honest unit of independence is the scenario.

CI computation is **opt-in via `with_ci=True`**. Sweep runs leave it off so the
hot path stays fast; post-hoc `eval-suite report --with-ci ...` reloads the
persisted ScoreRecords and annotates CIs without re-judging.
"""
from __future__ import annotations

import statistics
import warnings
from collections import defaultdict
from typing import Optional

import numpy as np
from scipy.stats import bootstrap

from .schemas import (
    AccuracyCell,
    AggregationRecord,
    ReportAxesCell,
    ScoreRecord,
    TotalsRow,
)


TIERS = ("easy", "middle", "hard")
QTYPES = ("A", "B", "C", "D", "E", "F")

DEFAULT_CI_LEVEL = 0.95
DEFAULT_N_RESAMPLES = 2000
DEFAULT_CI_METHOD = "BCa"
DEFAULT_SEED = 0


def cluster_bootstrap_ci(
    values_by_cluster: dict[str, list[float]],
    confidence_level: float = DEFAULT_CI_LEVEL,
    n_resamples: int = DEFAULT_N_RESAMPLES,
    method: str = DEFAULT_CI_METHOD,
    seed: int = DEFAULT_SEED,
) -> Optional[list[float]]:
    """Cluster bootstrap CI for the pooled mean.

    Resamples scenario clusters with replacement; each resample's statistic is
    the mean of all observations pooled from the chosen clusters. Returns
    `[lo, hi]` rounded to 2dp, or None if the CI is undefined (≤1 cluster).
    Degenerate constants short-circuit to `[v, v]`; BCa failures fall back to
    percentile.
    """
    cluster_values = [np.asarray(vs, dtype=float)
                      for vs in values_by_cluster.values() if vs]
    if len(cluster_values) < 2:
        return None
    pooled_all = np.concatenate(cluster_values)
    if np.all(pooled_all == pooled_all[0]):
        v = round(float(pooled_all[0]), 2)
        return [v, v]

    cluster_idx = np.arange(len(cluster_values))

    def stat(idx_sample, axis=-1):
        pooled = np.concatenate([cluster_values[int(i)] for i in idx_sample])
        return pooled.mean()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = bootstrap(
                (cluster_idx,), stat,
                confidence_level=confidence_level,
                n_resamples=n_resamples,
                random_state=seed,
                method=method,
                vectorized=False,
            )
        lo = float(res.confidence_interval.low)
        hi = float(res.confidence_interval.high)
    except Exception:
        if method == "BCa":
            return cluster_bootstrap_ci(values_by_cluster, confidence_level,
                                        n_resamples, method="percentile", seed=seed)
        return None
    if not np.isfinite(lo) or not np.isfinite(hi):
        return None
    return [round(lo, 2), round(hi, 2)]


def _mean_round(vals: list[float], n: int = 2) -> Optional[float]:
    if not vals:
        return None
    return round(sum(vals) / len(vals), n)


def _stdev_round(vals: list[float], n: int = 2) -> Optional[float]:
    if len(vals) < 2:
        return None
    return round(statistics.stdev(vals), n)


def _report_axis_value(rec: ScoreRecord, score_key: str) -> Optional[float]:
    axis = rec.scores.get(score_key)
    return axis.value if axis is not None else None


def _ci_method_tag(level: float, method: str) -> str:
    pct = int(round(level * 100))
    return f"cluster_bootstrap_{'bca' if method == 'BCa' else method.lower()}_{pct}"


def aggregate(records: list[ScoreRecord],
              run_summary_id: str = "default",
              *,
              with_ci: bool = False,
              ci_level: float = DEFAULT_CI_LEVEL,
              ci_n_resamples: int = DEFAULT_N_RESAMPLES,
              ci_method: str = DEFAULT_CI_METHOD,
              ci_seed: int = DEFAULT_SEED) -> AggregationRecord:
    # Per-cell, per-scenario value buckets — used for both the mean and (when
    # with_ci=True) the cluster bootstrap.

    # accuracy: acc_buckets[tier][qtype][scenario_id] = [values]
    acc_buckets: dict[str, dict[str, dict[str, list[float]]]] = \
        defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in records:
        for qtype, v in r.accuracy_by_qtype.items():
            acc_buckets[r.tier][qtype][r.scenario_id].append(v)

    accuracy_matrix: dict[str, dict[str, Optional[AccuracyCell]]] = {}
    for tier in TIERS:
        accuracy_matrix[tier] = {}
        for q in QTYPES:
            by_scen = acc_buckets[tier].get(q, {})
            flat = [v for vs in by_scen.values() for v in vs]
            if not flat:
                accuracy_matrix[tier][q] = None
                continue
            cell = AccuracyCell(
                accuracy=_mean_round(flat),
                n=len(flat),
                n_clusters=len(by_scen),
                stddev=_stdev_round(flat),
            )
            if with_ci:
                cell.ci = cluster_bootstrap_ci(by_scen,
                                               confidence_level=ci_level,
                                               n_resamples=ci_n_resamples,
                                               method=ci_method,
                                               seed=ci_seed)
            accuracy_matrix[tier][q] = cell

    # Report axes: by tier × scenario, three metrics each.
    axes_buckets: dict[str, dict[str, dict[str, list[float]]]] = \
        defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    # axes_buckets[tier]["coverage"|"faithfulness"|"quality"][scen_id] = [values]
    AXIS_KEY = {
        "coverage":     "keypoint_coverage",
        "faithfulness": "report_faithfulness",
        "quality":      "report_quality",
    }
    by_tier_records: dict[str, list[ScoreRecord]] = defaultdict(list)
    for r in records:
        by_tier_records[r.tier].append(r)
        for short, axis_key in AXIS_KEY.items():
            v = _report_axis_value(r, axis_key)
            if v is not None:
                axes_buckets[r.tier][short][r.scenario_id].append(v)

    report_axes: dict[str, Optional[ReportAxesCell]] = {}
    for tier in TIERS:
        recs = by_tier_records.get(tier, [])
        if not recs:
            report_axes[tier] = None
            continue
        per_metric: dict[str, list[float]] = {}
        for short in AXIS_KEY:
            per_metric[short] = [v for vs in axes_buckets[tier].get(short, {}).values()
                                 for v in vs]
        cell = ReportAxesCell(
            coverage=_mean_round(per_metric["coverage"]),
            faithfulness=_mean_round(per_metric["faithfulness"]),
            quality=_mean_round(per_metric["quality"]),
            n=len(recs),
            n_clusters=len({r.scenario_id for r in recs}),
        )
        for k, vs in per_metric.items():
            sd = _stdev_round(vs)
            if sd is not None:
                cell.stddev[k] = sd
        if with_ci:
            for k in AXIS_KEY:
                ci = cluster_bootstrap_ci(axes_buckets[tier].get(k, {}),
                                          confidence_level=ci_level,
                                          n_resamples=ci_n_resamples,
                                          method=ci_method,
                                          seed=ci_seed)
                if ci is not None:
                    cell.ci[k] = ci
        report_axes[tier] = cell

    # Suite-wide totals.
    all_metrics: dict[str, dict[str, list[float]]] = {
        "accuracy":     defaultdict(list),
        "coverage":     defaultdict(list),
        "faithfulness": defaultdict(list),
        "quality":      defaultdict(list),
    }
    AXIS_TOTALS_KEY = {
        "accuracy":     "keypoint_accuracy",
        "coverage":     "keypoint_coverage",
        "faithfulness": "report_faithfulness",
        "quality":      "report_quality",
    }
    for r in records:
        for short, axis_key in AXIS_TOTALS_KEY.items():
            v = _report_axis_value(r, axis_key)
            if v is not None:
                all_metrics[short][r.scenario_id].append(v)
    flat_totals = {k: [v for vs in vbc.values() for v in vs]
                   for k, vbc in all_metrics.items()}

    totals = TotalsRow(
        accuracy=_mean_round(flat_totals["accuracy"]),
        coverage=_mean_round(flat_totals["coverage"]),
        faithfulness=_mean_round(flat_totals["faithfulness"]),
        quality=_mean_round(flat_totals["quality"]),
        n=len(records),
        n_clusters=len({r.scenario_id for r in records}),
    )
    for k, vs in flat_totals.items():
        sd = _stdev_round(vs)
        if sd is not None:
            totals.stddev[k] = sd
    if with_ci:
        for k, vbc in all_metrics.items():
            ci = cluster_bootstrap_ci(vbc,
                                      confidence_level=ci_level,
                                      n_resamples=ci_n_resamples,
                                      method=ci_method,
                                      seed=ci_seed)
            if ci is not None:
                totals.ci[k] = ci
        if totals.ci:
            totals.ci_method = _ci_method_tag(ci_level, ci_method)

    total_judge_cost = sum(r.judge_cost_usd or 0.0 for r in records)
    return AggregationRecord(
        run_summary_id=run_summary_id,
        n_scenarios=len({r.scenario_id for r in records}),
        n_runs=len(records),
        accuracy_matrix=accuracy_matrix,
        report_axes=report_axes,
        totals=totals,
        total_judge_cost_usd=round(total_judge_cost, 4),
        ci_settings=(
            {
                "method":       _ci_method_tag(ci_level, ci_method),
                "level":        ci_level,
                "n_resamples":  ci_n_resamples,
                "seed":         ci_seed,
                "cluster":      "scenario_id",
            } if with_ci else None
        ),
    )


def render_ascii_matrix(agg: AggregationRecord) -> str:
    """Two-table rendering. When CIs are present, each row is followed by a
    `[lo, hi]` line indented to align under the means."""
    lines = [f"# Aggregation: {agg.run_summary_id}"]
    lines.append(f"  n_scenarios={agg.n_scenarios}  n_runs={agg.n_runs}  total_cost=${agg.total_judge_cost_usd:.3f}")
    if agg.ci_settings:
        lines.append(f"  ci: {agg.ci_settings['method']}  "
                     f"(n_resamples={agg.ci_settings['n_resamples']}, "
                     f"seed={agg.ci_settings['seed']})")

    # --- Accuracy matrix ---
    # Column width adapts to whether CIs are present.
    has_acc_ci = any(
        cell is not None and cell.ci is not None
        for tier in TIERS for cell in agg.accuracy_matrix[tier].values()
    )
    col_w = 16 if has_acc_ci else 7
    lines.append("")
    lines.append("## Accuracy by tier × question type (0-100)")
    header = "tier".ljust(8) + "".join(f"  {q:^{col_w}s}" for q in QTYPES)
    lines.append(header)
    lines.append("-" * len(header))
    for tier in TIERS:
        mean_row = tier.ljust(8)
        ci_row   = " " * 8
        any_ci = False
        for q in QTYPES:
            cell = agg.accuracy_matrix[tier][q]
            if cell is None or cell.accuracy is None:
                mean_row += "  " + "—".center(col_w)
                ci_row   += "  " + " ".center(col_w)
            else:
                mean_row += "  " + f"{cell.accuracy:5.1f}".center(col_w)
                if cell.ci is not None:
                    any_ci = True
                    ci_row += "  " + f"[{cell.ci[0]:.1f}, {cell.ci[1]:.1f}]".center(col_w)
                else:
                    ci_row += "  " + " ".center(col_w)
        lines.append(mean_row)
        if has_acc_ci and any_ci:
            lines.append(ci_row)

    # --- Report axes table ---
    lines.append("")
    lines.append("## Report axes by tier (0-100)")
    has_axes_ci = any(
        cell is not None and cell.ci
        for cell in agg.report_axes.values()
    )
    metric_w = 17 if has_axes_ci else 10
    sub_header = ("tier".ljust(8)
                  + f"  {'coverage':^{metric_w}s}  {'faithful.':^{metric_w}s}"
                  + f"  {'quality':^{metric_w}s}  {'n':^4s}")
    lines.append(sub_header)
    lines.append("-" * len(sub_header))
    for tier in TIERS:
        cell = agg.report_axes.get(tier)
        if cell is None:
            lines.append(tier.ljust(8) + "  " + "n/a".ljust(len(sub_header) - 10))
            continue
        def fmt(v):
            return f"{v:5.1f}" if v is not None else "  —  "
        mean_row = (tier.ljust(8)
                    + f"  {fmt(cell.coverage):^{metric_w}s}"
                    + f"  {fmt(cell.faithfulness):^{metric_w}s}"
                    + f"  {fmt(cell.quality):^{metric_w}s}"
                    + f"  {cell.n:^4d}")
        lines.append(mean_row)
        if has_axes_ci and cell.ci:
            def fmt_ci(k: str) -> str:
                ci = cell.ci.get(k)
                return f"[{ci[0]:.1f}, {ci[1]:.1f}]" if ci else " "
            ci_row = (" " * 8
                      + f"  {fmt_ci('coverage'):^{metric_w}s}"
                      + f"  {fmt_ci('faithfulness'):^{metric_w}s}"
                      + f"  {fmt_ci('quality'):^{metric_w}s}"
                      + "      ")
            lines.append(ci_row)

    # --- Totals ---
    lines.append("")
    t = agg.totals
    def fmtt(v):
        return f"{v:.2f}" if v is not None else "—"
    def fmt_metric(name: str, v: Optional[float]) -> str:
        s = f"{name}={fmtt(v)}"
        ci = t.ci.get(name)
        if ci is not None:
            s += f" [{ci[0]:.2f}, {ci[1]:.2f}]"
        return s
    header = f"Totals (n={t.n}, scenarios={t.n_clusters})"
    if t.ci_method:
        header += f"  ({t.ci_method})"
    lines.append(header + ":")
    lines.append("  " + "  ".join(fmt_metric(k, getattr(t, k))
                                   for k in ("accuracy", "coverage",
                                             "faithfulness", "quality")))
    return "\n".join(lines)
