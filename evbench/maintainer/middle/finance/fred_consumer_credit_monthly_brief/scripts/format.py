#!/usr/bin/env python3
"""Build instances for this scenario's this scenario.

    python scripts/format.py                 # every step, in order: timeseries -> gt
    python scripts/format.py timeseries    # one step
    python scripts/format.py gt [flags]    # …with that step's own flags
    python scripts/format.py all [flags]     # every step, flags forwarded to each
    python scripts/format.py --list          # list the steps

Merged from format_timeseries.py and format_gt.py. Each step keeps the argument
parser it had before, so every flag that used to work still works — pass it
after the step name.
"""
from __future__ import annotations
import csv
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import INSTANCES, QUERY_MONTHS, SERIES, TS_SOURCE
import os
import json
from _common import INSTANCES, QUERY_MONTHS
def _scenario_data_dir(script_file: str) -> Path:
    """Data directory for the scenario whose scripts/ contains `script_file`.

    Scripts live in evbench/maintainer/<tier>/<domain>/<id>/scripts/ while
    instances/ and source/ live under evbench/scenarios/.
    $TIMESAGE_DATA_ROOT overrides the data root.
    """
    spec = Path(script_file).resolve().parent.parent
    maintainer = spec.parents[2]
    rel = spec.relative_to(maintainer)
    return Path(os.environ.get("TIMESAGE_DATA_ROOT", maintainer.parent / "scenarios")) / rel

SCENARIO_DIR = _scenario_data_dir(__file__)
GT_SOURCE = SCENARIO_DIR / "gt_source"
MAINTAINER_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(MAINTAINER_ROOT / "lib"))
from narrative_extract import build_narrative_md_block, load_source_text  # noqa: E402


# --- step: timeseries ----------------------------------------------------


def load_observations(csv_path: Path, sid: str) -> dict[str, float]:
    out: dict[str, float] = {}
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        date_col = "observation_date" if "observation_date" in fieldnames else fieldnames[0]
        value_col = sid if sid in fieldnames else fieldnames[-1]
        for row in reader:
            d = row[date_col].strip()
            v = row[value_col].strip()
            if not d or v in ("", "."):
                continue
            try:
                out[d[:7]] = float(v)
            except ValueError:
                continue
    return out


def _step_timeseries() -> int:
    INSTANCES.mkdir(parents=True, exist_ok=True)
    by_series: dict[str, dict[str, float]] = {}
    months: set[str] = set()
    for short, sid, _col in SERIES:
        src = TS_SOURCE / f"{short}.csv"
        if not src.exists():
            print(f"MISSING: {src}", file=sys.stderr)
            return 1
        by_series[short] = load_observations(src, sid)
        months.update(by_series[short].keys())

    sorted_months = sorted(months)

    for q in QUERY_MONTHS:
        inst_dir = INSTANCES / q
        inst_dir.mkdir(parents=True, exist_ok=True)
        ts_path = inst_dir / "timeseries.csv"
        header = ["data_month"] + [col for _short, _sid, col in SERIES]
        with ts_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            for month in sorted_months:
                if month > q:
                    break
                row = [month]
                for short, _sid, _col in SERIES:
                    v = by_series[short].get(month)
                    row.append(f"{v:.2f}" if v is not None else "")
                w.writerow(row)
        print(f"wrote {ts_path}", file=sys.stderr)
    return 0


# --- step: gt ------------------------------------------------------------
def _f(v):
    if v in (None, "", "None"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _step_gt() -> int:
    if not INSTANCES.exists():
        print("Run `format.py timeseries` first", file=sys.stderr)
        return 1

    for q in QUERY_MONTHS:
        inst_dir = INSTANCES / q
        ts_path = inst_dir / "timeseries.csv"
        if not ts_path.exists():
            continue
        with ts_path.open() as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
        if len(rows) < 2:
            print(f"FEW ROWS for {q}", file=sys.stderr)
            continue
        col = {c: i for i, c in enumerate(header)}

        last = rows[-1]
        prev = rows[-2]
        total_t  = _f(last[col["total_millions"]])
        total_p  = _f(prev[col["total_millions"]])
        rev_t    = _f(last[col["revolving_millions"]])
        rev_p    = _f(prev[col["revolving_millions"]])
        nrev_t   = _f(last[col["nonrevolving_millions"]])
        nrev_p   = _f(prev[col["nonrevolving_millions"]])

        if total_t is None or total_p is None:
            print(f"missing total for {q}", file=sys.stderr)
            continue

        total_bn = round(total_t / 1000.0, 1)
        mom_bn   = round((total_t - total_p) / 1000.0, 1)
        g_t = 100.0 * (total_t - total_p) / total_p if total_p else 0.0

        # 5-year (60-month) baseline of MoM growth rates, taken over the
        # 60 rows immediately preceding the LATEST row (so excluding the
        # query month itself). Falls back to whatever is available
        # (minimum 12 rows of growth data).
        priors = rows[:-1]
        prior_growths: list[float] = []
        for i in range(1, len(priors)):
            tp = _f(priors[i-1][col["total_millions"]])
            tc = _f(priors[i][col["total_millions"]])
            if tp is None or tc is None or tp == 0:
                continue
            prior_growths.append(100.0 * (tc - tp) / tp)
        window = prior_growths[-60:]
        if len(window) < 12:
            window = prior_growths
        baseline = (sum(window) / len(window)) if window else 0.0
        vs_5yr = round(g_t - baseline, 2)

        # Dominant component: revolving vs nonrevolving by |MoM dollar change|.
        if rev_t is not None and rev_p is not None and \
           nrev_t is not None and nrev_p is not None:
            dr = abs(rev_t - rev_p)
            dn = abs(nrev_t - nrev_p)
            dom = "revolving" if dr >= dn else "nonrevolving"
        else:
            dom = "revolving"  # safe default; rare in this window

        rev_bn_t  = round(rev_t / 1000.0, 1) if rev_t is not None else None
        nrev_bn_t = round(nrev_t / 1000.0, 1) if nrev_t is not None else None
        rev_mom_bn  = round((rev_t - rev_p) / 1000.0, 1) \
            if rev_t is not None and rev_p is not None else None
        nrev_mom_bn = round((nrev_t - nrev_p) / 1000.0, 1) \
            if nrev_t is not None and nrev_p is not None else None

        # Reference report (LLM-judge target).
        mom_sign = "increased" if mom_bn > 0 else ("decreased" if mom_bn < 0 else "was unchanged")
        baseline_sign = "above" if vs_5yr > 0 else ("below" if vs_5yr < 0 else "in line with")
        summary = (
            f"In {last[0]}, total U.S. consumer credit stood at "
            f"${total_bn:.1f} billion, having {mom_sign} by "
            f"${mom_bn:+.1f} billion month-over-month. The month's "
            f"MoM growth rate was {baseline_sign} the trailing 5-year "
            f"average by {vs_5yr:+.2f} percentage points. The dominant "
            f"contributor to the change was the {dom} component."
        )

        gt = {
            "as_of_data_month": last[0],
            "total_consumer_credit_billions": total_bn,
            "mom_change_billions": mom_bn,
            "vs_5yr_avg_growth_pct": vs_5yr,
            "dominant_growth_component": dom,
            "report": summary,
        }
        (inst_dir / "ground_truth.json").write_text(
            json.dumps(gt, indent=2) + "\n"
        )

        ev_lines = [
            f"# Evidence -- FRED G.19 Consumer Credit brief ({q})",
            "",
            "## Source",
            f"- Data month: **{last[0]}**",
            "- FRED series: `TOTALSL` (total, millions of $), `REVOLSL` "
            "(revolving, millions of $), `NONREVSL` (nonrevolving, "
            "millions of $).",
            "- Raw CSVs in `gt_source/` (one per series, full history).",
            "",
            "## Computed quantities",
            f"- total_millions[t] = {total_t:.2f}  → total_consumer_credit_billions = {total_bn:.1f}",
            f"- total_millions[t-1] = {total_p:.2f} → mom_change_billions = {mom_bn:+.1f}",
            f"- this-month MoM growth rate g_t = {g_t:+.4f}%",
            f"- 5-year baseline mean growth rate = {baseline:+.4f}% "
            f"(over {len(window)} prior monthly observations)",
            f"- vs_5yr_avg_growth_pct = g_t - baseline = {vs_5yr:+.2f} pp",
        ]
        if rev_t is not None and rev_p is not None:
            ev_lines.append(
                f"- revolving Δ = {rev_t - rev_p:+.2f} million ($, "
                f"|Δ| = {abs(rev_t - rev_p):.2f})"
            )
        if nrev_t is not None and nrev_p is not None:
            ev_lines.append(
                f"- nonrevolving Δ = {nrev_t - nrev_p:+.2f} million ($, "
                f"|Δ| = {abs(nrev_t - nrev_p):.2f})"
            )
        ev_lines += [
            f"- dominant_growth_component = **{dom}**",
            "",
            "## Reference report (for llm_judge)",
            "",
            summary,
        ]
        # Append verbatim + trigger sentences from the G.19 release PDF.
        pdf_path = GT_SOURCE / f"{q}.pdf"
        src_text, pages = load_source_text(pdf_path)
        if src_text:
            ev_lines.append(build_narrative_md_block(
                source_ref=f"gt_source/{q}.pdf",
                source_text=src_text,
                pages=pages,
                verbatim_label=(
                    "Verbatim G.19 release excerpt "
                    "(release-page commentary / notes)"
                ),
                max_verbatim_chars=2500,
            ))
        (inst_dir / "gt_evidence.md").write_text("\n".join(ev_lines) + "\n")

        manifest = {
            "scenario_id": "fred_consumer_credit_monthly_brief",
            "as_of_data_month": last[0],
            "accessible_artifacts": [
                {
                    "path": "gt_source/total.csv",
                    "kind": "csv",
                    "description": "FRED TOTALSL full-history CSV",
                },
                {
                    "path": "gt_source/revolving.csv",
                    "kind": "csv",
                    "description": "FRED REVOLSL full-history CSV",
                },
                {
                    "path": "gt_source/nonrevolving.csv",
                    "kind": "csv",
                    "description": "FRED NONREVSL full-history CSV",
                },
            ],
            "note": "The same monthly CSVs that feed the timeseries also "
                    "carry the GT (the credit values). Brief fields are "
                    "computed directly from the last two rows of "
                    "timeseries.csv (plus a 60-month prior window for B5).",
        }
        (inst_dir / "visible_reports.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )

        print(f"wrote GT for {q}: total={total_bn:.1f}B mom={mom_bn:+.1f}B "
              f"vs5y={vs_5yr:+.2f}pp dom={dom}", file=sys.stderr)
    return 0

# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------

#: Execution order. The ground truth is derived from the series, so timeseries runs first.
STEPS = ("timeseries", "gt")

_STEP_FUNCS = {
    "timeseries": _step_timeseries,
    "gt": _step_gt,
}


def _run_step(step: str, args: list) -> int:
    """Invoke one step with `args` as its argv, then restore the real argv."""
    saved = sys.argv
    sys.argv = [f"{Path(__file__).name} {step}"] + list(args)
    try:
        return int(_STEP_FUNCS[step]() or 0)
    finally:
        sys.argv = saved


def main() -> int:
    argv = sys.argv[1:]

    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv and argv[0] == "--list":
        for step in STEPS:
            print(step)
        return 0

    if argv and argv[0] in STEPS:
        return _run_step(argv[0], argv[1:])

    # No step named: run all of them. Bare invocation passes no flags; an
    # explicit `all` forwards whatever follows to every step.
    rest = argv[1:] if (argv and argv[0] == "all") else []
    if argv and argv[0] != "all":
        print(f"unknown step {argv[0]!r}; expected one of {', '.join(STEPS)}, "
              f"or 'all'", file=sys.stderr)
        return 2

    for step in STEPS:
        rc = _run_step(step, rest)
        if rc:
            print(f"[{Path(__file__).name}] step {step!r} exited {rc}; stopping",
                  file=sys.stderr)
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
