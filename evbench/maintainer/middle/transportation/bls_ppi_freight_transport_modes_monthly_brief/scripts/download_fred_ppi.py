"""Download the 5 FRED-mirrored BLS PPI series used by this scenario.

For each series, the FRED CSV download endpoint is:
    https://fred.stlouisfed.org/graph/fredgraph.csv?id=<series_id>

The CSV has two columns: observation_date (YYYY-MM-DD, first-of-month)
and <series_id> (PPI value).

We pull each series via curl (Python urllib has been observed to time
out against the FRED edge intermittently) and write the bytes verbatim
to timeseries_source/<series_id>.csv. `format.py timeseries` reads all
five and emits per-instance cumulative CSVs.

Stage-2 ingestion. Stage-3 transformation lives in `format.py timeseries`.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from pathlib import Path

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



ROOT = _scenario_data_dir(__file__)
RAW_CSV_DIR = ROOT / "timeseries_source"

SERIES = {
    "PCU482111482111": "rail_freight",
    "PCU484121484121": "general_freight_trucking",
    "PCU483111483111": "deep_sea_freight",
    "PCU481111481111": "scheduled_air",
    "PCU488488": "transport_support",
}

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
USER_AGENT = "Mozilla/5.0 (compatible; TimeSage-EV/scaffold)"


def fetch_with_curl(url: str, dest: Path, attempts: int = 5) -> bool:
    if not shutil.which("curl"):
        print("curl not on PATH", file=sys.stderr)
        return False
    # FRED's HTTP/2 layer occasionally aborts streams (curl rc=92,
    # INTERNAL_ERROR). Retry a few times — usually one of them succeeds.
    last_rc = None
    for i in range(attempts):
        try:
            res = subprocess.run(
                ["curl", "-s", "-L", "--max-time", "60", "-o", str(dest), url],
                check=False, timeout=120,
            )
            last_rc = res.returncode
        except subprocess.TimeoutExpired:
            last_rc = -1
            continue
        if last_rc == 0 and dest.exists() and dest.stat().st_size >= 200:
            head = dest.read_bytes()[:64].decode("utf-8", errors="ignore")
            if "observation_date" in head:
                return True
    sz = dest.stat().st_size if dest.exists() else 0
    print(f"  miss: {url} (last rc={last_rc}, size={sz})", file=sys.stderr)
    return False


def main() -> int:
    RAW_CSV_DIR.mkdir(parents=True, exist_ok=True)
    ok = miss = 0
    for sid in SERIES:
        url = FRED_URL.format(sid=sid)
        dest = RAW_CSV_DIR / f"{sid}.csv"
        if fetch_with_curl(url, dest):
            print(f"  wrote {dest} ({dest.stat().st_size} bytes)")
            ok += 1
        else:
            miss += 1
    print(f"FRED PPI fetch: {ok} ok / {miss} miss")
    return 0 if miss == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
