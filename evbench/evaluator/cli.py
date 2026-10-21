"""CLI: score a single run, render reports.

Usage:
  eval-suite score <scenario_dir> <period> <run_record.json> [--mock-judge]
  eval-suite report <records_glob>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterable

from .aggregator import aggregate, render_ascii_matrix
from .judge import Judge, build_judge
from evbench.engine.tasks import load_scenario
from .schemas import AxisScore, RunRecord, ScoreRecord
from .scorers import accuracy, coverage, faithfulness, quality


REPORT_DIR = Path(__file__).resolve().parent / "reports"


def _load_run_record(path: Path) -> RunRecord:
    raw = json.loads(path.read_text())
    return RunRecord(**raw)


def _load_gt(scenario_dir: Path, period: str) -> dict:
    p = scenario_dir / "instances" / period / "ground_truth.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _question_types(scenario) -> list[str]:
    out = set()
    for t in scenario.question_tags:
        if t and t[0].upper() in "ABCDEF":
            out.add(t[0].upper())
    return sorted(out)


_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}
_MONTH_YEAR = re.compile(r"\b(" + "|".join(_MONTHS) + r"|"
                         + "|".join(m[:3] for m in _MONTHS) + r")\.?\s+(\d{4})\b", re.I)
_NUMBER = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?")
#: Most CSV rows the judge is shown, besides the header. A series this short
#: is shown whole, so claims over many rows ("the only extreme print of the
#: year", "the 12-month high") can be checked too.
MAX_CONTEXT_ROWS = 50


def _report_periods(report: str) -> str:
    """The report plus `YYYY-MM` for every "January 2023" it mentions, so
    month-name dates match a CSV's period labels."""
    extra = [f"{y}-{_MONTHS.get(m.lower()) or [v for k, v in _MONTHS.items() if k.startswith(m.lower())][0]:02d}"
             for m, y in _MONTH_YEAR.findall(report)]
    return report + "\n" + " ".join(extra)


def _report_numbers(report: str) -> list[tuple[float, int]]:
    """(value, decimals) of the data values a report cites. Only numbers with
    3+ significant digits count: thresholds like 0.5, small counts and years
    would match rows all over the history."""
    out = []
    for tok in _NUMBER.findall(report):
        raw = tok.replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        dec = len(raw.split(".")[1]) if "." in raw else 0
        if len(raw.lstrip("+-").replace(".", "").lstrip("0")) < 3:
            continue
        if dec == 0 and 1900 <= abs(v) <= 2100:
            continue
        out.append((v, dec))
    return out


def _relevant_rows(lines: list[str], report: str) -> list[tuple[int, str]]:
    """The CSV rows a report draws on: all of them for a short series; else
    the last two, every row whose period or date cell the report names, and
    every row holding a value the report cites (at the report's precision).
    In file order, capped; each as (0-based data-row index, line)."""
    if len(lines) <= 1:
        return []
    rows = lines[1:]
    if len(rows) <= MAX_CONTEXT_ROWS:
        return list(enumerate(rows))
    text = _report_periods(report)
    nums = _report_numbers(report)
    # Rows the report names by period/date, and the latest two, always go in;
    # rows matched only by a cited value fill the rest of the budget.
    keep = set(range(max(0, len(rows) - 2), len(rows)))
    by_value: list[int] = []
    for i, row in enumerate(rows):
        cells = [c.strip() for c in row.split(",")]
        if any(("-" in c and any(ch.isdigit() for ch in c) and c in text) for c in cells):
            keep.add(i)
            continue
        for c in cells:
            try:
                v = float(c)
            except ValueError:
                continue
            if any(round(v, d) == round(n, d) for n, d in nums):
                by_value.append(i)
                break
    for i in reversed(by_value):                  # most recent first
        if len(keep) >= MAX_CONTEXT_ROWS:
            break
        keep.add(i)
    return [(i, rows[i]) for i in sorted(keep)[-MAX_CONTEXT_ROWS:]]


def _build_tier2_excerpts(scenario_dir: Path, period: str, report: str = "") -> list[str]:
    """CSV rows the report draws on (see _relevant_rows) + prior-period file names.

    The judge verifies each claim against these. Showing only the last rows
    made every comparison with an earlier period — YoY, a 5-year baseline,
    a trailing window — unverifiable, so correct reports lost those facts.
    """
    excerpts: list[str] = []
    csv_path = scenario_dir / "instances" / period / "timeseries.csv"
    if csv_path.exists():
        text = csv_path.read_text().splitlines()
        if text:
            excerpts.append("timeseries.csv header: " + text[0])
            # Reports cite rows by number, as pandas does (0-based) or counting
            # from 1; both are given so either can be checked.
            for i, line in _relevant_rows(text, report):
                excerpts.append(f"timeseries.csv row {i} (0-based) / {i + 1} (1-based): {line}")
    gt_source = scenario_dir / "gt_source"
    if gt_source.is_dir():
        prior = []
        for f in sorted(gt_source.iterdir()):
            if not f.is_file():
                continue
            stem = f.stem
            for prefix in ("iata_passenger_", "iata_cargo_"):
                if stem.startswith(prefix):
                    stem = stem[len(prefix):]
                    break
            if stem < period:
                prior.append(stem)
        if prior:
            excerpts.append(f"prior-period gt_source files available: {prior[-6:]}")
    return excerpts


def _score_one(scenario_dir: Path, period: str, run: RunRecord,
               judge: Judge) -> ScoreRecord:
    scenario = load_scenario(scenario_dir)
    gt = _load_gt(scenario_dir, period)

    # Failure modes
    structural_only = False
    if not run.report:
        return ScoreRecord(
            run_id=run.run_id, scenario_id=scenario.scenario_id,
            tier=scenario.tier, period=period,
            question_types=_question_types(scenario),
            scores={},
            failure_mode="missing_report",
            pass_threshold=scenario.pass_threshold,
            judge=judge.describe(),
        )
    # JSON-schema validation of structured_answer
    required = (scenario.answer_schema.get("required") or [])
    if not all(k in run.structured_answer for k in required):
        structural_only = True

    t0 = time.time()
    scores: dict[str, AxisScore] = {}

    def judged(axis: str, fn) -> AxisScore:
        """Run one judge-backed axis; if any judge call failed for good, the
        axis is judge_unavailable rather than the zero the scorer computed."""
        judge.take_failures()
        res = fn()
        failed = judge.take_failures()
        if not failed:
            return res
        return AxisScore(name=axis, value=None, status="judge_unavailable",
                         detail={"judge_errors": failed[:5], "n_failed_calls": len(failed)})

    # 1. Keypoint Accuracy (structural — may be skipped if structural_only)
    if structural_only:
        scores["keypoint_accuracy"] = AxisScore(
            name="keypoint_accuracy", value=0.0, status="structural_only",
            detail={"reason": "structured_answer missing required keys"})
    else:
        scores["keypoint_accuracy"] = accuracy.score(run, scenario, gt, judge)
    # 2. Keypoint Coverage (report-side)
    scores["keypoint_coverage"] = judged(
        "keypoint_coverage", lambda: coverage.score(run, scenario, gt, judge))
    # 3. Faithfulness (report-side, tiered)
    ctx = _build_tier2_excerpts(scenario_dir, period, run.report)
    scores["report_faithfulness"] = judged(
        "report_faithfulness", lambda: faithfulness.score(run, scenario, gt, judge, ctx))
    # 4. Quality (report-side, tier rubric)
    scores["report_quality"] = judged(
        "report_quality", lambda: quality.score(run, scenario, gt, judge))

    # Aggregate: simple unweighted mean over scored axes (None excluded).
    # Each axis is on a 0-100 scale, so aggregate is also 0-100. An axis the
    # judge could not score leaves the run unscored: averaging the others
    # would pass or fail it on a different formula.
    unavailable = [a for a, s in scores.items() if s.status == "judge_unavailable"]
    vals = [s.value for s in scores.values() if s.value is not None]
    aggregate_score = (round(sum(vals) / len(vals), 2)
                       if vals and not unavailable else None)

    # Per-question-type slice of Accuracy: mean per-KP score within
    # each question type (the first letter of the keypoint's question_tag).
    acc_by_qtype = _accuracy_by_qtype(scores.get("keypoint_accuracy"))

    return ScoreRecord(
        run_id=run.run_id,
        scenario_id=scenario.scenario_id,
        tier=scenario.tier,
        period=period,
        question_types=_question_types(scenario),
        scores=scores,
        accuracy_by_qtype=acc_by_qtype,
        aggregate=aggregate_score,
        pass_threshold=scenario.pass_threshold,
        passed=bool(aggregate_score is not None and aggregate_score >= scenario.pass_threshold),
        judge=judge.describe(),
        judge_cost_usd=round(judge.total_cost_usd, 4),
        wall_time_ms=int((time.time() - t0) * 1000),
        structural_only=structural_only,
        failure_mode="judge_unavailable" if unavailable else None,
    )


def _accuracy_by_qtype(acc_axis: AxisScore | None) -> dict[str, float]:
    """Slice per-KP accuracy scores by question type (first letter of question_tag).

    Returns the unweighted mean score in 0-100 per qtype. Returns {} when the
    Accuracy axis is missing (e.g. structural_only failure)."""
    if acc_axis is None or not acc_axis.detail.get("per_kp"):
        return {}
    by_q: dict[str, list[float]] = {}
    for kp in acc_axis.detail["per_kp"]:
        tag = (kp.get("question_tag") or "").strip()
        if not tag:
            continue
        qtype = tag[0].upper()
        if qtype not in "ABCDEF":
            continue
        by_q.setdefault(qtype, []).append(kp["score"])
    return {qtype: round(sum(s) / len(s) * 100, 2) for qtype, s in by_q.items()}


def _judge(args: argparse.Namespace) -> Judge:
    return build_judge("mock" if args.mock_judge else "anthropic")


def cmd_score(args: argparse.Namespace) -> int:
    scenario_dir = Path(args.scenario_dir).resolve()
    run = _load_run_record(Path(args.run_record).resolve())
    judge = _judge(args)
    rec = _score_one(scenario_dir, args.period, run, judge)
    out_dir = REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{rec.run_id}.json"
    out_path.write_text(rec.model_dump_json(indent=2))
    print(f"wrote {out_path}")
    print(json.dumps(rec.model_dump(), indent=2)[:2000])
    return 0


def _aggregate_kwargs_from_args(args: argparse.Namespace) -> dict:
    """Build the with_ci/ci_* kwargs for aggregate() from CLI flags."""
    kwargs = {"with_ci": bool(getattr(args, "with_ci", False))}
    if kwargs["with_ci"]:
        kwargs.update(
            ci_level=args.ci_level,
            ci_n_resamples=args.ci_n_resamples,
            ci_method=args.ci_method,
            ci_seed=args.ci_seed,
        )
    return kwargs


def _add_ci_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--with-ci", action="store_true",
                   help="annotate cluster-bootstrap CIs (resamples scenarios)")
    p.add_argument("--ci-level", type=float, default=0.95)
    p.add_argument("--ci-n-resamples", type=int, default=2000)
    p.add_argument("--ci-method", choices=["BCa", "percentile", "basic"], default="BCa")
    p.add_argument("--ci-seed", type=int, default=0)


def cmd_report(args: argparse.Namespace) -> int:
    import glob as _glob
    pattern = args.records_glob
    records: list[ScoreRecord] = []
    for s in _glob.glob(pattern):
        records.append(ScoreRecord.model_validate_json(Path(s).read_text()))
    if not records:
        print(f"no records matched {pattern}")
        return 1
    agg = aggregate(records, run_summary_id=args.summary_id or "ad_hoc",
                    **_aggregate_kwargs_from_args(args))
    print(render_ascii_matrix(agg))
    if args.out:
        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(agg.model_dump_json(indent=2))
        print(f"\nwrote {out_path}")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="eval-suite", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("score", help="score a single agent run")
    ps.add_argument("scenario_dir")
    ps.add_argument("period")
    ps.add_argument("run_record")
    ps.add_argument("--mock-judge", action="store_true")
    ps.set_defaults(func=cmd_score)

    pr = sub.add_parser("report",
                        help="aggregate from existing score-record files; "
                             "supports post-hoc CI annotation via --with-ci")
    pr.add_argument("records_glob")
    pr.add_argument("--summary-id", default=None)
    pr.add_argument("--out", default=None,
                    help="path to write the AggregationRecord JSON (optional)")
    _add_ci_flags(pr)
    pr.set_defaults(func=cmd_report)

    args = p.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
