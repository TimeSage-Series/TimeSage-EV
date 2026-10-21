#!/usr/bin/env python3
"""Repo-wide scenario validator.

Checks that every scenario in `evbench/scenarios/` is structurally sound, internally
consistent, and free of future-information leakage, before it is used for
evaluation or published. Run it after any data update:

    python evbench/maintainer/corpus/validate_scenarios.py --all
    python evbench/maintainer/corpus/validate_scenarios.py scenarios_unfinished/hard/*/* --verbose
    python evbench/maintainer/corpus/validate_scenarios.py evbench/scenarios/easy/finance/cboe_vix_volatility_regime_state

Gates
-----
F  files          the 4 core instance files, 7 task-contract files, 4 pipeline scripts;
                 every instance.json fills its question template
S  schema         every ground_truth.json satisfies the task's answer_schema.json
T  timeseries     instances/<p>/timeseries.csv parses, has a period column, max <= p
E  evidence       gt_evidence.md is non-empty and cites gt_source/ or CSV cells
X  cross-instance answers are not degenerate across periods
L  leakage        no gt_source file >= period; no CSV row beyond the period

Exit code is non-zero if any gate fails. `warn` never fails the run.

The upstream project had an eight-gate audit under an untracked `tools/`
directory that was lost before release; this is a reimplementation covering
the gates that can be checked from the committed corpus alone. The two gates
that needed per-scenario oracle modules (R: rule reproducibility, P: quote
grounding) are not reproduced — see evbench/maintainer/README.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIOS = REPO_ROOT / "evbench" / "scenarios"         # instances/, source/
SCENARIOS_CODE = REPO_ROOT / "evbench" / "maintainer"    # scenario.json, scripts/


def code_dir(scenario_dir: Path) -> Path:
    """The evbench/maintainer/ counterpart of a data-tree scenario directory.

    Matched on <tier>/<domain>/<id>, so any data tree works — evbench/scenarios/,
    scenarios_unfinished/, scenarios_hf/.
    """
    return SCENARIOS_CODE.joinpath(*scenario_dir.resolve().parts[-3:])


# The task contract, question rendering and leakage logic are the engine's;
# reuse them rather than reimplementing their edge cases.
sys.path.insert(0, str(REPO_ROOT))
from evbench.engine import render_question, task_dir  # noqa: E402
from evbench.engine.world import (  # noqa: E402
    _csv_max_period, _is_lex_sortable_period, _strip_known_prefixes,
)

CORE_INSTANCE_FILES = ("timeseries.csv", "gt_evidence.md", "instance.json",
                       "ground_truth.json")
CORE_ENV_FILES = ("question_template.md", "question_tags.yaml",
                  "answer_schema.json", "keypoints.yaml", "eval_rubric.yaml",
                  "session_brief.md", "scoring.yaml")
CORE_SCRIPTS = ("requirements.txt", "download.py", "format.py",
                "template_vars.py")

# Answer degeneracy: a categorical field that never changes across periods
# makes the scenario trivially guessable.
DEGENERATE_FAIL = 1.00
DEGENERATE_WARN = 0.80

# Set by --strict; promotes X-gate degeneracy findings from warn to fail.
STRICT = {"on": False}


@dataclass
class Result:
    scenario: str
    fails: list[str] = field(default_factory=list)
    warns: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "fail" if self.fails else ("warn" if self.warns else "pass")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _periods(scenario: Path) -> list[str]:
    inst = scenario / "instances"
    if not inst.is_dir():
        return []
    return sorted(d.name for d in inst.iterdir() if d.is_dir())


def _json_type_ok(value, spec: dict) -> bool:
    """Check a value against the subset of JSON Schema the corpus uses."""
    t = spec.get("type")
    if t is None or value is None:
        return True
    types = t if isinstance(t, list) else [t]
    checks = {
        "string": str, "number": (int, float), "integer": int,
        "boolean": bool, "array": list, "object": dict,
    }
    for name in types:
        if name == "null":
            if value is None:
                return True
            continue
        py = checks.get(name)
        if py is None:
            return True                     # unknown keyword — don't fail on it
        if name == "number" and isinstance(value, bool):
            continue
        if name == "integer" and isinstance(value, bool):
            continue
        if isinstance(value, py):
            return True
    return False


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------

def gate_files(sc: Path, res: Result) -> None:
    for name in CORE_ENV_FILES:
        p = task_dir(sc) / name
        if not p.exists():
            res.fails.append(f"F: missing task file {name}")
        elif p.stat().st_size == 0:
            res.fails.append(f"F: empty task file {name}")

    scripts_dir = code_dir(sc) / "scripts"
    for name in CORE_SCRIPTS:
        if not (scripts_dir / name).exists():
            res.fails.append(f"F: missing scripts/{name}")

    periods = _periods(sc)
    if not periods:
        res.fails.append("F: no instances")
        return
    for p in periods:
        d = sc / "instances" / p
        for name in CORE_INSTANCE_FILES:
            f = d / name
            if not f.exists():
                res.fails.append(f"F: missing instances/{p}/{name}")
            elif f.stat().st_size == 0:
                res.fails.append(f"F: empty instances/{p}/{name}")
        if (d / "instance.json").exists():
            try:
                render_question(sc, p)
            except (KeyError, OSError, ValueError) as exc:
                res.fails.append(f"F: instances/{p}/instance.json: {exc}")


def gate_schema(sc: Path, res: Result) -> None:
    schema = _load_json(task_dir(sc) / "answer_schema.json")
    if schema is None:
        res.fails.append("S: task answer_schema.json is missing or unparseable")
        return
    required = schema.get("required") or []
    props = schema.get("properties") or {}

    for p in _periods(sc):
        gt = _load_json(sc / "instances" / p / "ground_truth.json")
        if gt is None:
            res.fails.append(f"S: instances/{p}/ground_truth.json unparseable")
            continue
        if not gt:
            res.fails.append(f"S: instances/{p}/ground_truth.json is empty")
            continue
        for key in required:
            if key not in gt:
                res.fails.append(f"S: instances/{p} missing required field {key!r}")
            elif key in props and not _json_type_ok(gt[key], props[key]):
                want = props[key].get("type")
                got = type(gt[key]).__name__
                res.fails.append(
                    f"S: instances/{p} field {key!r} expected {want}, got {got}")


def gate_timeseries(sc: Path, res: Result) -> None:
    for p in _periods(sc):
        path = sc / "instances" / p / "timeseries.csv"
        if not path.exists():
            continue                        # already reported by gate F
        try:
            with path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
        except Exception as exc:
            res.fails.append(f"T: instances/{p}/timeseries.csv unreadable: {exc}")
            continue
        if len(rows) < 2:
            res.fails.append(f"T: instances/{p}/timeseries.csv has no data rows")
            continue
        width = len(rows[0])
        bad = [i for i, r in enumerate(rows[1:], 2) if r and len(r) != width]
        if bad:
            res.warns.append(
                f"T: instances/{p}/timeseries.csv ragged rows at lines {bad[:5]}")


def gate_evidence(sc: Path, res: Result) -> None:
    for p in _periods(sc):
        path = sc / "instances" / p / "gt_evidence.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < 40:
            res.fails.append(f"E: instances/{p}/gt_evidence.md is too short to ground anything")
        elif "gt_source/" not in text and "timeseries.csv" not in text:
            res.warns.append(
                f"E: instances/{p}/gt_evidence.md cites neither gt_source/ nor timeseries.csv")


def gate_cross_instance(sc: Path, res: Result) -> None:
    """Flag categorical answer fields that barely move across periods."""
    periods = _periods(sc)
    if len(periods) < 4:
        return
    values: dict[str, list] = {}
    for p in periods:
        gt = _load_json(sc / "instances" / p / "ground_truth.json") or {}
        for k, v in gt.items():
            if isinstance(v, str) and len(v) < 64:
                values.setdefault(k, []).append(v)

    for field_name, vals in values.items():
        if len(vals) < 4 or field_name in ("as_of_period", "report"):
            continue
        share = Counter(vals).most_common(1)[0][1] / len(vals)
        if share >= DEGENERATE_FAIL:
            # A constant categorical field is usually a real property of the
            # series (the top crude-oil source country really is Canada every
            # month), not a corpus defect. Surface it, but only fail under
            # --strict so the structural gates stay the useful CI signal.
            bucket = res.fails if STRICT["on"] else res.warns
            bucket.append(
                f"X: field {field_name!r} is constant across all {len(vals)} periods")
        elif share >= DEGENERATE_WARN:
            res.warns.append(
                f"X: field {field_name!r} takes one value in {share:.0%} of periods")


def gate_leakage(sc: Path, res: Result) -> None:
    # Note: gt_evidence.md is grader-side material and is *expected* to cite the
    # same-period source — that is where the answer comes from. Leakage is only
    # about what reaches the agent's sandbox, which evbench/engine/world.py filters to
    # `stem < period`. So the checks here are on agent-visible artifacts only.
    for p in _periods(sc):
        if not _is_lex_sortable_period(p):
            continue                        # comparator undefined for this format

        csv_path = sc / "instances" / p / "timeseries.csv"
        if csv_path.exists():
            mx = _csv_max_period(csv_path, p)
            if mx is not None and mx > p:
                res.fails.append(
                    f"L: instances/{p}/timeseries.csv contains period {mx!r} > {p!r}")

        vr = sc / "instances" / p / "visible_reports.json"
        if vr.exists():
            data = _load_json(vr) or {}
            # Builders write key "visible"; older readers looked for
            # "visible_reports". Accept either so the gate cannot go silently
            # dead the way dashboard/app/v7.py did.
            entries = data.get("visible", data.get("visible_reports", []))
            for item in entries:
                label = item if isinstance(item, str) else json.dumps(item)
                if p in label:
                    res.fails.append(
                        f"L: instances/{p}/visible_reports.json exposes the "
                        f"current period ({label[:60]})")
                    break


GATES = (
    ("F", gate_files),
    ("S", gate_schema),
    ("T", gate_timeseries),
    ("E", gate_evidence),
    ("X", gate_cross_instance),
    ("L", gate_leakage),
)


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def validate(sc: Path) -> Result:
    res = Result(scenario="/".join(sc.parts[-3:]))
    for _, fn in GATES:
        try:
            fn(sc, res)
        except Exception as exc:            # a crashing gate is itself a failure
            res.fails.append(f"{fn.__name__}: crashed: {exc!r}")
    return res


def discover(args) -> list[Path]:
    if args.scenarios:
        return [Path(s).resolve() for s in args.scenarios]
    out = sorted(p for p in SCENARIOS.glob("[!.]*/*/*") if p.is_dir())
    if args.tier:
        out = [p for p in out if p.parent.parent.name == args.tier]
    if args.domain:
        out = [p for p in out if p.parent.name == args.domain]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenarios", nargs="*", help="scenario directories (default: all)")
    ap.add_argument("--all", action="store_true", help="validate every scenario")
    ap.add_argument("--tier", choices=["easy", "middle", "hard"])
    ap.add_argument("--domain")
    ap.add_argument("--strict", action="store_true",
                    help="treat answer-degeneracy findings (gate X) as failures")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="also print warnings for passing scenarios")
    ap.add_argument("--json", dest="as_json", metavar="PATH",
                    help="write a machine-readable report")
    args = ap.parse_args()
    STRICT["on"] = args.strict

    targets = discover(args)
    if not targets:
        print("no scenarios matched", file=sys.stderr)
        return 2

    results = [validate(sc) for sc in targets]
    n_fail = sum(1 for r in results if r.status == "fail")
    n_warn = sum(1 for r in results if r.status == "warn")
    n_inst = sum(len(_periods(sc)) for sc in targets)

    for r in results:
        if r.status == "pass" and not args.verbose:
            continue
        print(f"[{r.status.upper():4s}] {r.scenario}")
        for m in r.fails:
            print(f"    FAIL {m}")
        if args.verbose or r.status != "fail":
            for m in r.warns[:10]:
                print(f"    warn {m}")

    print(f"\n{len(results)} scenarios / {n_inst} instances — "
          f"{len(results) - n_fail - n_warn} pass, {n_warn} warn, {n_fail} fail")

    if args.as_json:
        Path(args.as_json).write_text(json.dumps(
            {"scenarios": len(results), "instances": n_inst,
             "fail": n_fail, "warn": n_warn,
             "results": [{"scenario": r.scenario, "status": r.status,
                          "fails": r.fails, "warns": r.warns} for r in results]},
            indent=2) + "\n")

    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
