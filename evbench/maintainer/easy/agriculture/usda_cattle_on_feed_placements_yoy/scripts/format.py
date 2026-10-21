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
import argparse
import csv
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, INSTANCES  # noqa: E402
from _common import (  # noqa: E402
    INSTANCES, SERIES_FIRST, release_month_label, data_month_label,
)


# --- step: timeseries ----------------------------------------------------

# Levels only. USDA's signed YoY % is deliberately left out: its sign IS the
# answer, so shipping it would turn the task into a column lookup. The agent
# has to find the same-month prior-year row and compare placements itself.
CSV_COLUMNS = [
    "release_label", "release_year", "release_month",
    "data_month_name", "prior_year",
    "placements_million",
]


def _row(label: str, parsed: dict) -> dict:
    yr, mo = label.split("-")
    return {
        "release_label":       label,
        "release_year":        int(yr),
        "release_month":       int(mo),
        "data_month_name":     parsed["data_month_name"],
        "prior_year":          parsed["prior_year"],
        "placements_million":  parsed["placements_million"],
    }


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-months", required=True,
                    help="Comma-separated YYYY-MM release months")
    args = ap.parse_args()

    all_rows: dict[str, dict] = {}
    for jf in sorted(TS_SOURCE.glob("*.json")):
        label = jf.stem
        all_rows[label] = _row(label, json.loads(jf.read_text()))
    if not all_rows:
        raise SystemExit("[error] no parsed JSON in timeseries_source/")
    sorted_labels = sorted(all_rows)

    targets = [s.strip() for s in args.instance_months.split(",") if s.strip()]
    INSTANCES.mkdir(parents=True, exist_ok=True)
    n = 0
    for target in targets:
        if target not in all_rows:
            print(f"[warn] {target}: not in parsed set", flush=True); continue
        history = [lbl for lbl in sorted_labels if SERIES_FIRST <= lbl <= target]
        out_dir = INSTANCES / target
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "timeseries.csv"
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            w.writeheader()
            for lbl in history:
                w.writerow(all_rows[lbl])
        n += 1
        latest = all_rows[history[-1]]
        print(f"[ok]   {target}: {len(history)} rows; latest "
              f"placements_million={latest['placements_million']}", flush=True)
    print(f"[done] wrote {n} per-instance CSVs")
    return 0


# --- step: gt ------------------------------------------------------------
def _year_earlier(label: str) -> str:
    """Release twelve months before `label`; it covers the same data month."""
    return f"{int(label[:4]) - 1:04d}{label[4:]}"


def direction_from_csv(csv_path: Path, label: str) -> tuple[str, dict, dict]:
    """The YoY class an agent can derive from timeseries.csv alone.

    Compares this release's placements with the release a year earlier.
    Raises ValueError when that row is missing from the CSV.
    """
    with csv_path.open() as fh:
        rows = {r["release_label"]: r for r in csv.DictReader(fh)}
    cur = rows[label]
    prior = rows.get(_year_earlier(label))
    if prior is None or prior["data_month_name"] != cur["data_month_name"]:
        raise ValueError(f"no same-month prior-year row "
                         f"(release_label={_year_earlier(label)}) in timeseries.csv")
    a, b = float(cur["placements_million"]), float(prior["placements_million"])
    if a > b:
        return "above_prior_year", cur, prior
    if a < b:
        return "below_prior_year", cur, prior
    return "equal_to_prior_year", cur, prior


def _step_gt() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-months", required=True)
    args = ap.parse_args()

    targets = [s.strip() for s in args.instance_months.split(",") if s.strip()]
    n = 0
    failed: list[str] = []
    for label in targets:
        out_dir = INSTANCES / label
        csv_path = out_dir / "timeseries.csv"
        if not csv_path.exists():
            print(f"[skip] {label}: no timeseries.csv", file=sys.stderr); continue
        # The answer comes from the USDA headline phrase in the parsed release.
        parsed = json.loads((TS_SOURCE / f"{label}.json").read_text())
        answer = parsed["placements_yoy_class"]

        # Self-check: the CSV carries levels only, so the headline class must be
        # reproducible from them. If it is not, the instance is unanswerable from
        # its own inputs and must not be built — drop any GT a previous run left.
        try:
            from_csv, cur, prior = direction_from_csv(csv_path, label)
            problem = None if from_csv == answer else (
                f"USDA headline says {answer} but timeseries.csv gives {from_csv} "
                f"({prior['placements_million']} -> {cur['placements_million']} "
                f"million head)")
        except ValueError as e:
            problem = str(e)
        if problem:
            print(f"[fail] {label}: {problem}", file=sys.stderr)
            for stale in ("ground_truth.json", "gt_evidence.md"):
                (out_dir / stale).unlink(missing_ok=True)
            failed.append(label); continue

        yr, mo = int(label[:4]), int(label[5:])
        gt = {
            "placements_yoy_class": answer,
            "report": "",
        }
        (out_dir / "ground_truth.json").write_text(
            json.dumps(gt, indent=2) + "\n")

        evidence = (
            "# Ground-truth evidence -- USDA NASS Cattle on Feed Placements YoY\n\n"
            f"## Instance release month: {release_month_label(yr, mo)} ({label})\n\n"
            f"- **Cover month (data month)**: {data_month_label(yr, mo)}\n"
            f"- **Placements in feedlots**: {cur['placements_million']} million head "
            f"in {data_month_label(yr, mo)} vs {prior['placements_million']} million "
            f"head in {data_month_label(yr - 1, mo)}\n"
            f"- **YoY direction**: `{answer}`\n"
            f"- USDA headline: \"{parsed['verbatim_phrase']}\"\n"
            f"- Source rows in `timeseries.csv`: "
            f"`release_label={label}` and `release_label={prior['release_label']}` "
            f"(both `data_month_name={cur['data_month_name']}`)\n"
            f"- Applied rule (placements vs the same data month one year earlier):\n"
            f"  - higher -> `above_prior_year`\n"
            f"  - lower -> `below_prior_year`\n"
            f"  - equal -> `equal_to_prior_year`\n\n"
            "## Traceability\n\n"
            f"- Raw PDF: `gt_source/{label}.pdf` "
            f"(USDA NASS Cattle on Feed monthly report)\n"
            f"- Source landing: https://esmis.nal.usda.gov/publication/cattle-feed\n"
        )
        (out_dir / "gt_evidence.md").write_text(evidence)
        n += 1
        print(f"[ok]   {label}: -> {answer}", flush=True)
    print(f"[done] wrote {n} ground-truth files")
    if failed:
        print(f"[fail] {len(failed)} instance(s) not answerable from timeseries.csv: "
              f"{', '.join(failed)}", file=sys.stderr)
        return 1
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
