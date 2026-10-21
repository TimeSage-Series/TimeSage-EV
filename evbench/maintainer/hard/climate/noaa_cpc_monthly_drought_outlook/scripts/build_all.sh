#!/usr/bin/env bash
# Run the full instantiation pipeline end-to-end. Idempotent.
#
# Prerequisites:
#   - python3 with `requests` installed (see requirements.txt)
#   - network access to www.cpc.ncep.noaa.gov and usdmdataservices.unl.edu
#
# Usage:
#   bash scripts/build_all.sh
#
# Outputs:
#   - gt_source/<YYYY-MM>.html           24 MDO narratives
#   - timeseries_source/conus_*.csv      one CONUS USDM history
#   - instances/<YYYY-MM>/{question.md, answer_schema.json,
#                          timeseries.csv, ground_truth.json,
#                          gt_evidence.md, visible_reports.json}
set -euo pipefail
cd "$(dirname "$0")/.."

START=2024-06
END=2026-05

echo "== 1. Download MDO HTML narratives =="
python3 scripts/download_gt.py --start "$START" --end "$END"

echo "== 2. Download CONUS USDM weekly history =="
python3 scripts/download_timeseries.py --instance-start "$START" --instance-end "$END"

echo "== 3. Format per-instance timeseries.csv =="
python3 scripts/format_timeseries.py --instance-start "$START" --instance-end "$END"

echo "== 4. Render per-instance question.md + answer_schema.json =="
python3 scripts/rephrase_question.py --instance-start "$START" --instance-end "$END"

echo "== 5. Build visible_reports.json manifests =="
python3 scripts/build_visible_reports.py --instance-start "$START" --instance-end "$END"

echo "== 6. Parse MDO -> ground_truth.json + gt_evidence.md =="
python3 scripts/format_gt.py --instance-start "$START" --instance-end "$END"

echo "Done. Run scripts/validate.py to verify V4/V7/V10."
