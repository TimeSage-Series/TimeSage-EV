"""Build the sandbox working directory for one (scenario, period).

v2: every world is a self-contained tempfile.mkdtemp directory used as a
context manager. The agent subprocess gets cwd=root and never sees anything
outside. Strict period truncation: gt_source < period; timeseries.csv max
period <= period.

"""
from __future__ import annotations

import csv
import logging
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from .tasks import task_dir

log = logging.getLogger(__name__)

# Periods are sortable as plain strings under our naming convention
# ("2024-04", "2024-wk20", etc.). When this stops being true, swap in a
# scenario-provided comparator.
_GT_SOURCE_PREFIXES = ("iata_passenger_", "iata_cargo_")


@dataclass
class WorldDir:
    """A built sandbox.

    `root` is the directory the agent treats as its working dir. `base` is
    the tempdir parent (containing `root` and any sibling artifacts like
    `stderr.log` written by the worker subprocess).
    """
    root: Path
    base: Path
    files: list[str]
    scenario_dir: Path
    period: str
    cutoff: Optional[str] = None
    preserved_on_failure: bool = False


_strip_lock = threading.Lock()


def _strip_known_prefixes(stem: str) -> str:
    for prefix in _GT_SOURCE_PREFIXES:
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return stem


_PERIOD_COL_PRIORITY = (
    "period_label", "period", "as_of", "week_ending", "report_date",
    "date", "week",
)


def _shape_compatible(value: str, period_hint: str) -> bool:
    """Both values share a separator AND the same character class for the
    leading token (digits/alpha). 'season_label' style '1950-DJF' is not
    shape-compatible with '2026-03', so we won't try to compare them.
    """
    if not value or not period_hint:
        return False
    if ("-" in period_hint) != ("-" in value):
        return False
    if period_hint.split("-")[0].isdigit() != value.split("-")[0].isdigit():
        return False
    # Trailing token: digits-vs-alpha mismatch means different scheme.
    if "-" in period_hint:
        tail_h = period_hint.split("-", 1)[1]
        tail_v = value.split("-", 1)[1]
        if tail_h.isdigit() != tail_v.isdigit() and "wk" not in (tail_h + tail_v):
            return False
    return True


def _csv_max_period(csv_path: Path, period_hint: str) -> Optional[str]:
    """Return the max value in the column most likely to be the period.

    Priority: known period column names first (period_label, period, as_of,
    …). If none match, fall back to a column whose first value is
    shape-compatible with `period_hint`. Returns None when no usable column
    can be identified — caller treats that as 'check skipped'.
    """
    if not csv_path.exists():
        return None
    with csv_path.open() as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return None
        lower = [h.lower() for h in header]
        rows = list(reader)
        period_col: Optional[int] = None
        for name in _PERIOD_COL_PRIORITY:
            if name in lower:
                idx = lower.index(name)
                if rows and idx < len(rows[0]) and _shape_compatible(
                        rows[0][idx].strip(), period_hint):
                    period_col = idx
                    break
        if period_col is None and rows:
            for i, v in enumerate(rows[0]):
                if _shape_compatible(v.strip(), period_hint):
                    period_col = i
                    break
        if period_col is None:
            return None
        max_seen: Optional[str] = None
        for row in rows:
            if not row or period_col >= len(row):
                continue
            v = row[period_col].strip()
            if not v:
                continue
            if max_seen is None or v > max_seen:
                max_seen = v
        return max_seen


_LEX_SORTABLE_PERIOD = re.compile(
    r"^\d{4}(?:-(?:\d{1,2}|w\d{1,2}|W\d{1,2}|wk\d{1,2}|Q[1-4]|H[12]))?"
    r"(?:-\d{1,2})?$"
)


def _is_lex_sortable_period(period: str) -> bool:
    """Lex sort equals calendar sort for YYYY-MM, YYYY-MM-DD, YYYY-wkNN
    style. Returns False for month-name labels like '2024-August01' (BoE,
    FOMC) where lex sort != calendar sort.
    """
    return bool(_LEX_SORTABLE_PERIOD.match(period or ""))


def assert_no_future_leakage(root: Path, period: str) -> None:
    """Belt-and-braces: walk the sandbox and reject any file whose embedded
    period is >= the report period (strictly < for gt_source). Raises
    AssertionError on leakage. This catches copy bugs that the copy step
    failed to. Skipped for non-lex-sortable period formats (callers must
    enforce safety another way for those scenarios)."""
    if not _is_lex_sortable_period(period):
        return
    gt_dir = root / "gt_source"
    if gt_dir.is_dir():
        for f in gt_dir.iterdir():
            if not f.is_file():
                continue
            stem = _strip_known_prefixes(f.stem)
            if stem >= period:
                raise AssertionError(
                    f"future leakage: gt_source/{f.name} (stem={stem!r}) "
                    f"is >= report period {period!r}"
                )
    csv_path = root / "timeseries.csv"
    if csv_path.exists():
        max_p = _csv_max_period(csv_path, period)
        if max_p is not None and max_p > period:
            raise AssertionError(
                f"future leakage: timeseries.csv contains period {max_p!r} > {period!r}"
            )


def _materialize(root: Path, scenario_dir: Path, period: str) -> list[str]:
    files: list[str] = []
    inst = scenario_dir / "instances" / period
    src_csv = inst / "timeseries.csv"
    if src_csv.exists():
        shutil.copy2(src_csv, root / "timeseries.csv")
        files.append("timeseries.csv")

    schema = task_dir(scenario_dir) / "answer_schema.json"
    if schema.exists():
        shutil.copy2(schema, root / "answer_schema.json")
        files.append("answer_schema.json")

    gt_src = scenario_dir / "gt_source"
    if gt_src.is_dir():
        out_gt = root / "gt_source"
        out_gt.mkdir(parents=True, exist_ok=True)
        for f in sorted(gt_src.iterdir()):
            if not f.is_file():
                continue
            stem = _strip_known_prefixes(f.stem)
            if stem >= period:
                continue                                 # strictly < period
            dest = out_gt / f"{stem}{f.suffix}"
            shutil.copy2(f, dest)
            files.append(f"gt_source/{dest.name}")
    return files


@contextmanager
def build_world(scenario_dir: Path, period: str,
                run_id: Optional[str] = None,
                leave_on_failure: bool = True,
                ) -> Iterator[WorldDir]:
    """Build a sandbox; clean on success, preserve on failure.

    Concurrency: each call gets its own tempfile.mkdtemp, so no two workers
    ever touch the same path. The whole thing is OS-atomic.
    """
    base = Path(tempfile.mkdtemp(prefix=f"timesage_world_{run_id or 'run'}_"))
    root = base / "root"
    root.mkdir(parents=True, exist_ok=True)

    try:
        files = _materialize(root, scenario_dir, period)
        assert_no_future_leakage(root, period)
    except BaseException:
        if leave_on_failure:
            log.warning("sandbox materialize failed; preserved at %s", base)
        else:
            shutil.rmtree(base, ignore_errors=True)
        raise

    world = WorldDir(root=root, base=base, files=files,
                     scenario_dir=scenario_dir, period=period,
                     cutoff=period, preserved_on_failure=False)
    try:
        yield world
    except BaseException:
        if leave_on_failure:
            log.warning("agent run failed; sandbox preserved at %s", base)
            world.preserved_on_failure = True
            raise
        shutil.rmtree(base, ignore_errors=True)
        raise
    else:
        shutil.rmtree(base, ignore_errors=True)


def refresh_world(world: WorldDir, period: str) -> list[str]:
    """Advance a built sandbox to `period` in place (episode mode).

    The environment's files are rewritten for `period`; gt_source/ is rebuilt
    from scratch so nothing at or after `period` survives from an earlier
    refresh, whatever order periods arrive in. Anything else the agent wrote
    in the sandbox is kept, like the rest of its memory.
    """
    shutil.rmtree(world.root / "gt_source", ignore_errors=True)
    world.files = _materialize(world.root, world.scenario_dir, period)
    assert_no_future_leakage(world.root, period)
    world.period = world.cutoff = period
    return world.files


def teardown_world(world: WorldDir) -> None:
    """Manual teardown (for callers not using the context manager).

    Safe to call repeatedly; idempotent.
    """
    base = world.base
    if base.exists() and "timesage_world" in str(base):
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Multi-turn API — interface only, v1 raises NotImplementedError.
# ---------------------------------------------------------------------------

class World:
    """Multi-turn world stub. v1 is single-turn; these methods are kept so
    that future scenarios can extend WorldDir without breaking call sites."""

    def __init__(self, world_dir: WorldDir):
        self._wd = world_dir

    def step(self, action):
        raise NotImplementedError("v1 is single-turn; multi-turn arrives in v2.x")

    def reset(self) -> None:
        raise NotImplementedError("v1 is single-turn; multi-turn arrives in v2.x")

    def snapshot(self):
        raise NotImplementedError("v1 is single-turn; multi-turn arrives in v2.x")
