#!/usr/bin/env python3
"""Resolve the argument list each pipeline step needs, for batch drivers.

`download.py` and `format.py` dispatch to steps that kept their original
argument parsers, and those parsers disagree: of the 120 download steps, 58
require a period range and 62 take none. A batch driver therefore cannot just
run `download.py` — it has to know what each step wants.

The range itself comes from `scenario.json`: `coverage.first` and
`coverage.last` are exactly the values the flags expect.

Flags are read from the source rather than from `--help`, because several
scripts open the network before argparse runs and `--help` hangs on them.

    python evbench/maintainer/pipeline/scenario_cmd.py download cboe_vix_volatility_regime_state
        timeseries
        gt	--start	2025-W47	--end	2026-W18

One line per step, in execution order: the step name, then tab-separated
arguments. Prints nothing and exits 1 if the scenario is unknown.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIOS_CODE = REPO_ROOT / "evbench" / "maintainer"
#: Released corpus, then the tiers still being built.
REFERENCE_ROOTS = (REPO_ROOT / "evbench" / "scenarios", REPO_ROOT / "scenarios_unfinished")

STEP_FUNCS = {"timeseries": "_step_timeseries", "gt": "_step_gt"}

#: Script each `kind` resolves arguments for, when not `<kind>.py`.
SCRIPT_OF = {"vars": "template_vars.py"}

#: How to fill each required flag from scenario.json `coverage`.
FLAG_VALUES = {
    "--start": "first", "--end": "last",
    "--instance-start": "first", "--instance-end": "last",
    "--start-week": "first", "--end-week": "last",
    "--start-month": "first", "--end-month": "last",
    "--years-from": "first_year",
    # Two scenarios want the whole period list rather than a range. The
    # authoritative list is the instance directory names, which is also what
    # source/<period>/ mirrors.
    "--instance-months": "period_list",
    "--instance-dates": "period_list",
    "--instance-list": "period_list",
}


def required_flags(src: str, func: str) -> list[str]:
    """Flags of `func`'s parser that have no default and no action."""
    out = []
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.FunctionDef) and node.name == func):
            continue
        for call in ast.walk(node):
            if not (isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "add_argument"):
                continue
            if not call.args or not isinstance(call.args[0], ast.Constant):
                continue
            name = call.args[0].value
            if not isinstance(name, str) or not name.startswith("--"):
                continue
            kw = {k.arg: k.value for k in call.keywords}
            explicit = (isinstance(kw.get("required"), ast.Constant)
                        and kw["required"].value is True)
            defaulted = "default" in kw and not (
                isinstance(kw["default"], ast.Constant) and kw["default"].value is None)
            if explicit or not (defaulted or "action" in kw):
                out.append(name)
    return sorted(set(out))


def optional_flags(src: str, func: str) -> set[str]:
    """Every flag `func`'s parser declares, required or not."""
    out = set()
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.FunctionDef) and node.name == func):
            continue
        for call in ast.walk(node):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "add_argument"
                    and call.args and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)
                    and call.args[0].value.startswith("--")):
                out.add(call.args[0].value)
    return out


def steps_of(src: str) -> list[str]:
    """The STEPS tuple the merged script declares, in execution order."""
    for node in ast.parse(src).body:
        if (isinstance(node, ast.Assign) and node.targets
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "STEPS"):
            return [e.value for e in node.value.elts]
    return ["timeseries", "gt"]


#: Scenarios whose CLI takes labels from a different domain than their instance
#: directory names. noaa_cpc_oni_global_enso_phase names its folders by the
#: season's centred month (MAM 2024 -> "2024-04") but its parser wants the
#: season code, and rejects the folder name outright.
def _season_labels(sc: Path, periods: list[str]) -> list[str] | None:
    """Translate instance folder names back into the labels the CLI expects."""
    common = sc / "scripts" / "_common.py"
    if not common.exists() or "SEASON_CENTERED_MONTH" not in common.read_text():
        return None
    ns: dict = {}
    for node in ast.parse(common.read_text()).body:
        if (isinstance(node, ast.Assign) and node.targets
                and getattr(node.targets[0], "id", "") == "SEASON_CENTERED_MONTH"):
            ns = ast.literal_eval(node.value)
            break
    if not ns:
        return None
    by_month = {v: k for k, v in ns.items()}
    out = []
    for p in periods:
        try:
            year, month = p.split("-")
            out.append(f"{year}-{by_month[int(month)]}")
        except (ValueError, KeyError):
            return None
    return out


def advance_end(fmt: str, target: "dt.date") -> str | None:
    """The label for `target` in this scenario's period format.

    Extending coverage means moving the download's end bound forward, and the
    bound has to be written in whatever dialect the scenario's CLI speaks.
    Returns None for formats that cannot be computed — Bank of England and ECB
    label their files by monetary-policy meeting date, and those dates come
    from a published calendar, not from arithmetic.
    """
    iso = target.isocalendar()
    if fmt == "year_month":
        return f"{target.year}-{target.month:02d}"
    if fmt == "year_month_m":
        return f"{target.year}-M{target.month:02d}"
    if fmt == "year_month_day":
        return target.isoformat()
    if fmt == "iso_week":
        return f"{iso[0]}-W{iso[1]:02d}"
    if fmt == "year_week_us":
        return f"{iso[0]}-wk{iso[1]:02d}"
    if fmt == "iso_week_range":
        # Pairs start on odd weeks: 2025-W01-02, 2025-W03-04, …
        lo = iso[1] if iso[1] % 2 else iso[1] - 1
        return f"{iso[0]}-W{lo:02d}-{lo + 1:02d}"
    return None


def extend_periods(periods: list, fmt: str, target: "dt.date") -> list:
    """Append the periods between the last known one and `target`.

    Two scenarios take the whole period list rather than a range
    (`--instance-months`, `--instance-dates`), and that list is read off the
    existing instance directories. Left alone it can only ever re-fetch what is
    already there, so extending coverage would silently do nothing.
    """
    if not periods:
        return periods
    out = list(periods)
    if fmt == "year_month":
        y, m = (int(x) for x in out[-1].split("-")[:2])
        while (y, m) < (target.year, target.month):
            m += 1
            if m > 12:
                y, m = y + 1, 1
            out.append(f"{y}-{m:02d}")
    elif fmt == "year_month_day":
        last = dt.date.fromisoformat(out[-1])
        step = dt.timedelta(days=7)             # these are weekly release dates
        while last + step <= target:
            last += step
            out.append(last.isoformat())
    return out


def find_scenario(scenario_id: str) -> Path | None:
    hits = [p for p in SCENARIOS_CODE.glob(f"*/*/{scenario_id}") if p.is_dir()]
    return hits[0] if hits else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["download", "format", "vars"])
    ap.add_argument("scenario")
    ap.add_argument("--only", choices=["timeseries", "gt"],
                    help="emit just this step")
    ap.add_argument("--until", metavar="YYYY-MM-DD",
                    help="extend the end bound to this date, rewritten into the "
                         "scenario's period format")
    ap.add_argument("--extra", default="",
                    help="space-separated flags to append where the step declares them")
    args = ap.parse_args()

    sc = find_scenario(args.scenario)
    if sc is None:
        print(f"unknown scenario: {args.scenario}", file=sys.stderr)
        return 1
    script = sc / "scripts" / SCRIPT_OF.get(args.kind, f"{args.kind}.py")
    if not script.exists():
        print(f"missing {script}", file=sys.stderr)
        return 1

    card = json.loads((sc / "scenario.json").read_text())
    coverage = card.get("coverage") or {}
    # The two steps want different starts. The ground-truth step fetches one
    # report per instance, so it is bounded by the instance window. The
    # time-series step has to reach back as far as the instance CSV does —
    # cdc_us_rsv_positivity_seasonal_phase_weekly answers a seasonal-phase
    # question from 358 weekly rows going back to 2019, and starting it at the
    # instance window silently cut six years off that baseline.
    # The authoritative period list is the reference corpus's instance
    # directories. Falling through to source/<period>/ is a last resort: a
    # capture-dated snapshot folder there would otherwise masquerade as the
    # scenario's only period.
    rel = sc.relative_to(SCENARIOS_CODE)
    periods = []
    data_root = Path(os.environ.get("TIMESAGE_DATA_ROOT", REFERENCE_ROOTS[0]))
    for base in (*(r / rel / "instances" for r in REFERENCE_ROOTS),
                 data_root / rel / "instances",
                 data_root / rel / "source"):
        if base.is_dir():
            periods = sorted(d.name for d in base.iterdir() if d.is_dir())
            if periods:
                break

    labels = _season_labels(sc, periods) or periods

    end_override = None
    if args.until:
        target = dt.date.fromisoformat(args.until)
        end_override = advance_end(card.get("period", {}).get("format", ""), target)
        if end_override is None:
            print(f"{args.scenario}: period format "
                  f"{card.get('period', {}).get('format')!r} cannot be advanced "
                  f"by date; leaving the end bound alone", file=sys.stderr)

    # The end bound is computed in folder dialect; a scenario whose CLI speaks
    # season codes needs it translated like every other label.
    if end_override and labels is not periods:
        end_override = (_season_labels(sc, [end_override]) or [None])[0]

    if args.until and labels is periods:
        periods = labels = extend_periods(
            periods, card.get("period", {}).get("format", ""),
            dt.date.fromisoformat(args.until))

    gt_values = {
        "period_list": ",".join(labels) or None,
        "first": labels[0] if labels else coverage.get("first"),
        "last": end_override or (labels[-1] if labels else coverage.get("last")),
        "first_year": (coverage.get("first") or "")[:4] or None,
    }
    # When the CLI speaks a different label domain than the folder names, the
    # series start has to be translated too — mixing "2024-04" with "2026-FMA"
    # in one invocation is worse than either alone.
    series_start = coverage.get("series_first") or coverage.get("first")
    if labels is not periods:                     # a translation was applied
        try:
            series_start = labels[periods.index(series_start)]
        except ValueError:
            series_start = labels[0] if labels else series_start
    ts_values = dict(gt_values, first=series_start,
                     first_year=(series_start or "")[:4] or None)

    src = script.read_text()
    extra = [e for e in args.extra.split() if e]

    # template_vars.py is a single-step script: one parser, in main().
    if args.kind == "vars":
        argv = []
        for flag in required_flags(src, "main"):
            key = FLAG_VALUES.get(flag)
            if key is None or gt_values.get(key) is None:
                print(f"{args.scenario}/vars: cannot fill required {flag}",
                      file=sys.stderr)
                return 2
            argv += [flag, gt_values[key]]
        print("\t".join(["vars"] + argv))
        return 0

    for step in steps_of(src):
        if args.only and step != args.only:
            continue
        func = STEP_FUNCS[step]
        values = ts_values if step == "timeseries" else gt_values
        argv: list[str] = []
        for flag in required_flags(src, func):
            key = FLAG_VALUES.get(flag)
            if key is None or values.get(key) is None:
                print(f"{args.scenario}/{step}: cannot fill required {flag}",
                      file=sys.stderr)
                return 2
            argv += [flag, values[key]]
        declared = optional_flags(src, func)
        for flag in extra:
            if flag.split("=")[0] in declared:
                argv.append(flag)
        print("\t".join([step] + argv))

    # Fourteen scenarios keep a specialised downloader alongside the merged
    # one — bulletin archives, FRED series that need their own call, a URL
    # discovery pass. They were never part of download_gt.py/download_
    # timeseries.py, so the merge did not absorb them, and a batch driver that
    # only runs download.py silently leaves those scenarios' PDFs unfetched.
    if args.kind == "download" and not args.only:
        for aux in sorted((sc / "scripts").glob("download_*.py")) + \
                   sorted((sc / "scripts").glob("discover_*.py")):
            aux_src = aux.read_text()
            argv = []
            for flag in required_flags(aux_src, "main"):
                key = FLAG_VALUES.get(flag)
                if key is None or gt_values.get(key) is None:
                    print(f"{args.scenario}/{aux.name}: cannot fill {flag}",
                          file=sys.stderr)
                    return 2
                argv += [flag, gt_values[key]]
            print("\t".join([f"@{aux.name}"] + argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
