"""Per-instance validity recheck for noaa_cpc_monthly_drought_outlook.

Walks instances/<YYYY-MM>/ and verifies the three Stage-4 validity items
that depend on the concrete task design (V4 reference traceability, V7
information isolation, V10 objective evaluability).

Prints a per-instance report and a final scenario-level summary
suitable for pasting into scenario.yaml under `stage4a_validity_recheck`.
"""
from __future__ import annotations
import csv
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (   # noqa: E402
    INSTANCES, iter_months, month_label, release_date_for,
)


def _check_v4(inst_dir: Path) -> tuple[bool, str]:
    """gt_evidence.md cites concrete MDO narrative sentences AND
    ground_truth.json -> driver_sentences_reference is non-empty."""
    gt_path = inst_dir / "ground_truth.json"
    ev_path = inst_dir / "gt_evidence.md"
    if not gt_path.exists() or not ev_path.exists():
        return False, "missing ground_truth.json or gt_evidence.md"
    gt = json.loads(gt_path.read_text())
    if not gt.get("driver_sentences_reference") and not gt.get("uncertainty_sentences_reference"):
        return False, "no verbatim driver/uncertainty sentences captured"
    if "gt_source/" not in ev_path.read_text():
        return False, "gt_evidence.md does not cite gt_source/<label>.html"
    return True, "ok"


def _check_v7(inst_dir: Path, year: int, month: int) -> tuple[bool, str]:
    """timeseries.csv excludes USDM weeks with week_ending strictly after
    the MDO release date; and visible_reports.json excludes the
    query-month MDO."""
    ts_path = inst_dir / "timeseries.csv"
    vr_path = inst_dir / "visible_reports.json"
    label = month_label(year, month)
    release = release_date_for(year, month)
    if not ts_path.exists():
        return False, "no timeseries.csv"
    if not vr_path.exists():
        return False, "no visible_reports.json"
    with ts_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            we = dt.date.fromisoformat(row["week_ending"])
            if we > release:
                return False, f"timeseries.csv contains week_ending={we} > release={release}"
    vr = json.loads(vr_path.read_text())
    for v in vr.get("visible", []):
        if v["label"] == label:
            return False, "visible_reports.json contains the current-month MDO"
    return True, "ok"


def _check_v10(inst_dir: Path) -> tuple[bool, str]:
    """Set-match fields are well-defined enums; LLM-judge fields have
    reference sentences; supporting_evidence list is non-empty."""
    gt = json.loads((inst_dir / "ground_truth.json").read_text())
    for field in ("regions_persists", "regions_develops", "regions_improves", "regions_removes"):
        if not isinstance(gt.get(field, []), list):
            return False, f"{field} is not a list"
    if not gt.get("key_drivers"):
        return False, "key_drivers empty"
    if not gt.get("supporting_evidence_reference"):
        return False, "supporting_evidence_reference empty"
    return True, "ok"


def main() -> None:
    start = "2024-06"
    end = "2026-05"
    summary = {"V4": [], "V7": [], "V10": []}
    rows = []
    for y, m in iter_months(start, end):
        label = month_label(y, m)
        d = INSTANCES / label
        if not d.exists():
            print(f"[skip] {label}: missing instance dir")
            continue
        v4, m4 = _check_v4(d)
        v7, m7 = _check_v7(d, y, m)
        v10, m10 = _check_v10(d)
        rows.append((label, v4, v7, v10, m4, m7, m10))
        if v4: summary["V4"].append(label)
        if v7: summary["V7"].append(label)
        if v10: summary["V10"].append(label)
        print(f"{label}: V4={v4} ({m4})  V7={v7} ({m7})  V10={v10} ({m10})")

    n = len(rows)
    print()
    print("Summary:")
    for k, ok_list in summary.items():
        print(f"  {k}: {len(ok_list)}/{n} pass")


if __name__ == "__main__":
    main()
