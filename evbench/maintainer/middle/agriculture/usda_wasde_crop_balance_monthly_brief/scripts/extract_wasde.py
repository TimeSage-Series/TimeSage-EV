"""Parse every WASDE PDF in gt_source/ into the JSON fixture consumed by
`format.py timeseries`.

Output: timeseries_source/wasde_extracted.json with shape
  {
    "YYYY-MM": {
      "release_year": int, "release_month": int, "marketing_year": str,
      "corn_us_ending_stocks_mbu": float,
      "soybeans_us_ending_stocks_mbu": float,
      "wheat_us_ending_stocks_mbu": float,
      "corn_us_yield_bua": float,         # hard scenario columns
      "soybeans_us_yield_bua": float,
      "wheat_us_yield_bua": float,
      "corn_us_exports_mbu": float,
      "soybeans_us_exports_mbu": float,
      "wheat_us_exports_mbu": float,
      "corn_world_ending_stocks_mmt": float,
      "soybeans_world_ending_stocks_mmt": float,
      "wheat_world_ending_stocks_mmt": float
    },
    ...
  }

The middle scenario only consumes a subset of these columns
(`format.py timeseries` filters by COLUMNS), so emitting the full set keeps
both scenarios on a single fixture format.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import GT_SOURCE, TS_SOURCE  # noqa: E402
from _pdf_parser import parse_wasde  # noqa: E402


def main() -> int:
    if not GT_SOURCE.exists():
        print(f"missing gt_source: {GT_SOURCE}. Run download_wasde.py first.")
        return 1
    pdfs = sorted(GT_SOURCE.glob("*.pdf"))
    if not pdfs:
        print("no PDFs in gt_source/")
        return 1
    out: dict[str, dict] = {}
    for pdf_path in pdfs:
        # filename is YYYY-MM.pdf
        label = pdf_path.stem  # "YYYY-MM"
        try:
            year_s, month_s = label.split("-")
            year = int(year_s)
            month = int(month_s)
        except ValueError:
            print(f"  skip (bad name): {pdf_path}")
            continue
        try:
            parsed = parse_wasde(pdf_path, release_month=month)
        except Exception as exc:  # noqa: BLE001
            print(f"  parse error {label}: {exc}")
            continue
        # Build the per-period record. Drop intermediate marketing_year keys.
        rec = {
            "release_year": year,
            "release_month": month,
            "marketing_year": parsed.get("marketing_year"),
        }
        for col in (
            "corn_us_ending_stocks_mbu",
            "soybeans_us_ending_stocks_mbu",
            "wheat_us_ending_stocks_mbu",
            "corn_us_yield_bua", "soybeans_us_yield_bua", "wheat_us_yield_bua",
            "corn_us_exports_mbu", "soybeans_us_exports_mbu", "wheat_us_exports_mbu",
            "corn_world_ending_stocks_mmt",
            "soybeans_world_ending_stocks_mmt",
            "wheat_world_ending_stocks_mmt",
        ):
            v = parsed.get(col)
            if v is not None:
                rec[col] = v
        out[label] = rec
        print(f"  parsed {label}")
    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    fixture = TS_SOURCE / "wasde_extracted.json"
    fixture.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"wrote {fixture} ({len(out)} releases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
