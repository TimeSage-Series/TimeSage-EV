#!/usr/bin/env python3
"""Download this scenario's source artifacts.

    python scripts/download.py                 # every step, in order: timeseries -> gt
    python scripts/download.py timeseries    # one step
    python scripts/download.py gt [flags]    # …with that step's own flags
    python scripts/download.py all [flags]     # every step, flags forwarded to each
    python scripts/download.py --list          # list the steps

Merged from download_timeseries.py and download_gt.py. Each step keeps the argument
parser it had before, so every flag that used to work still works — pass it
after the step name.
"""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import TS_SOURCE, SERIES, FRED_BASE  # noqa: E402
import json
import re
import time
import urllib.request
import pypdf
from _common import GT_SOURCE, HEADERS, iter_months, month_label, START_LABEL, END_LABEL  # noqa: E402


# --- step: timeseries ----------------------------------------------------


def _step_timeseries() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    TS_SOURCE.mkdir(parents=True, exist_ok=True)
    ok = 0
    for label, series_id in SERIES.items():
        out = TS_SOURCE / f"{series_id}.csv"
        if out.exists() and out.stat().st_size > 200 and not args.force:
            print(f"[skip] {label}/{series_id}", flush=True)
            ok += 1
            continue
        url = f"{FRED_BASE}{series_id}"
        print(f"[fetch] {url}", flush=True)
        r = subprocess.run(
            ["curl", "-sSL", "--max-time", "30", "-o", str(out), url],
            check=False,
        )
        if r.returncode != 0 or not out.exists() or out.stat().st_size < 200:
            print(f"[err] {label}/{series_id} rc={r.returncode}", flush=True)
            continue
        print(f"[ok] {label}/{series_id}: {out.stat().st_size} bytes", flush=True)
        ok += 1
    return 0 if ok == len(SERIES) else 1


# --- step: gt ------------------------------------------------------------
TARGET = "https://apps.fas.usda.gov/psdonline/circulars/production.pdf"
CDX = (
    "http://web.archive.org/cdx/search/cdx"
    "?url=apps.fas.usda.gov/psdonline/circulars/production.pdf"
    "&filter=statuscode:200"
    "&filter=mimetype:application/pdf"
    "&output=json&limit=2000&from=20240101&to=20260601"
)

MASTHEAD_RE = re.compile(r"WAP\s+(\d{1,2})-(\d{2})", re.IGNORECASE)


def fetch_text(url: str, timeout: int = 90) -> str | None:
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            wait = 6 * (attempt + 1)
            print(f"  [retry {attempt+1}] {e}; sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
    return None


def fetch_pdf(url: str, dest: Path, timeout: int = 120) -> bool:
    rc = subprocess.run(
        ["curl", "-sSL", "-A", HEADERS["User-Agent"], "--max-time", str(timeout),
         "-o", str(dest), url],
        check=False,
    ).returncode
    if rc != 0 or not dest.exists() or dest.stat().st_size < 50_000:
        return False
    with dest.open("rb") as f:
        if f.read(4) != b"%PDF":
            return False
    return True


def parse_masthead_month(pdf_path: Path) -> str | None:
    """Return YYYY-MM from first-page WAP masthead, or None."""
    try:
        pdf = pypdf.PdfReader(str(pdf_path))
        text = pdf.pages[0].extract_text() or ""
    except Exception:
        return None
    m = MASTHEAD_RE.search(text)
    if not m:
        return None
    mo, yy = m.group(1), m.group(2)
    try:
        mo_int = int(mo)
        yy_int = int(yy)
        if 1 <= mo_int <= 12 and 0 <= yy_int <= 99:
            return f"20{yy_int:02d}-{mo_int:02d}"
    except ValueError:
        pass
    return None


def get_cdx() -> list[tuple[str, str, str]]:
    body = fetch_text(CDX, timeout=90)
    if not body or not body.strip().startswith("["):
        print(f"  [cdx-err] empty response", file=sys.stderr)
        return []
    try:
        rows = json.loads(body)
    except Exception as e:
        print(f"  [cdx-parse-err] {e}", file=sys.stderr)
        return []
    if not rows:
        return []
    header = rows[0]
    ts_i = header.index("timestamp")
    url_i = header.index("original")
    digest_i = header.index("digest")
    return [(r[ts_i], r[url_i], r[digest_i]) for r in rows[1:]]


def _step_gt() -> int:
    GT_SOURCE.mkdir(parents=True, exist_ok=True)

    print("[step1] fetching CDX of WAP PDF snapshots", file=sys.stderr)
    snaps = get_cdx()
    print(f"[step1] got {len(snaps)} CDX rows", file=sys.stderr)
    if not snaps:
        print("[fatal] no CDX rows; abort", file=sys.stderr)
        return 1

    # Group by digest — each unique digest is one bulletin month.
    by_digest: dict[str, list[tuple[str, str]]] = {}
    for ts, url, digest in snaps:
        by_digest.setdefault(digest, []).append((ts, url))
    print(f"[step1] {len(by_digest)} unique digests", file=sys.stderr)

    saved_months: set[str] = set()
    targets = {month_label(d) for d in iter_months(START_LABEL, END_LABEL)}

    # Pre-pass: see which months are already on disk + parse them.
    for f in GT_SOURCE.glob("*.pdf"):
        lbl_from_name = f.stem
        masthead = parse_masthead_month(f)
        if masthead and masthead in targets:
            if lbl_from_name != masthead:
                # Rename to match masthead.
                new_path = GT_SOURCE / f"{masthead}.pdf"
                if new_path.exists():
                    f.unlink()
                else:
                    f.rename(new_path)
                print(f"  [rename] {lbl_from_name}.pdf -> {masthead}.pdf", file=sys.stderr)
            saved_months.add(masthead)
        elif masthead is None:
            print(f"  [skip-parse] {f.name}: no masthead", file=sys.stderr)
        else:
            # Masthead falls outside target window; leave file for now.
            saved_months.add(lbl_from_name)

    # Now iterate unique digests, download new ones, parse, save.
    # Sort digests by earliest timestamp to maintain a stable processing order.
    digest_list = sorted(by_digest.items(), key=lambda kv: kv[1][0][0])
    tmp_root = GT_SOURCE / "_tmp"
    tmp_root.mkdir(exist_ok=True)
    try:
        for digest, capture_list in digest_list:
            capture_list.sort()
            ts, orig = capture_list[len(capture_list) // 2]  # middle capture
            tmp_path = tmp_root / f"{digest}.pdf"
            if not tmp_path.exists() or tmp_path.stat().st_size < 50_000:
                snap_url = f"https://web.archive.org/web/{ts}id_/{orig}"  # raw, no Wayback wrapping
                # Use the standard wrapped URL first; raw 'id_' is fragile.
                snap_url_w = f"https://web.archive.org/web/{ts}/{orig}"
                ok = fetch_pdf(snap_url_w, tmp_path, timeout=120)
                if not ok:
                    print(f"  [err] digest={digest[:8]} failed to download", file=sys.stderr)
                    if tmp_path.exists():
                        tmp_path.unlink()
                    time.sleep(2.0)
                    continue
                time.sleep(2.0)
            masthead = parse_masthead_month(tmp_path)
            if not masthead:
                print(f"  [no-masthead] digest={digest[:8]}; ts={ts}", file=sys.stderr)
                continue
            if masthead not in targets:
                print(f"  [out-of-window] digest={digest[:8]} masthead={masthead}",
                      file=sys.stderr)
                continue
            if masthead in saved_months:
                # Already have this month from a prior capture.
                continue
            dst = GT_SOURCE / f"{masthead}.pdf"
            tmp_path.replace(dst)
            saved_months.add(masthead)
            print(f"  [ok]   {masthead} <- digest={digest[:8]} ts={ts}", file=sys.stderr)
    finally:
        # Cleanup tmp dir.
        for f in tmp_root.glob("*.pdf"):
            f.unlink()
        try:
            tmp_root.rmdir()
        except OSError:
            pass

    n = len([f for f in GT_SOURCE.glob("*.pdf") if f.stem in targets])
    print(f"saved {n} WAP PDFs to {GT_SOURCE} ({sorted(targets - saved_months)} missing)",
          file=sys.stderr)
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
