"""`source/<period>/` addressing for the scenario pipeline scripts.

Source artifacts used to be split into `gt_source/` and `timeseries_source/` —
by which stage consumed them, not by what they were. That duplicated 33 MB
across 23 scenarios (the same PDF stored twice) and separated files that
describe the same period. They now live in one tree, organised by period:

    source/2024-01/ckeg0124.pdf      one period's artifacts, together
    source/2024-01/2024-01.pdf
    source/food_price_indices_data.csv   whole-history file — no period folder

`SourceTree` keeps the 60 pipeline scripts working against that layout
unchanged. They only ever do five things to these paths — `/`, `.glob`,
`.mkdir`, `.parent`, `.exists` — so the shim implements exactly those:

    GT_SOURCE / f"{label}.pdf"     -> source/<label>/<label>.pdf   (write)
    TS_SOURCE.glob("ckeg*.pdf")    -> every match across all period dirs (read)

Writes route by period; reads flatten the tree back. That asymmetry is the
whole point: a download script naming one file per period lands each in its own
folder, while `format.py` globbing for `ckeg*.pdf` still sees all 40 at once.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

__all__ = ["SourceTree", "period_for"]

#: A capture of a landing page. The date says when it was fetched, so it does
#: not place the file in a period.
# Any name ending in a full ISO date is a capture: `oni-2026-08-17.ascii.txt`
# holds the whole 1950-onward series, and the date says when it was fetched.
# Restricting this to landing/dashboard names filed those snapshots under a
# period that does not exist, which then became the scenario's only "period".
_CAPTURE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
#: `global-climate-202310`
_TRAILING_YYYYMM = re.compile(r"(?:^|[-_])(\d{4})(0[1-9]|1[0-2])$")
#: Publisher release codes: `ckeg0124` (Chicken and Eggs, 01/24), `wasde0122`.
#: The prefix length varies — pinning it to four letters missed every WASDE PDF.
_PUBLISHER_CODE = re.compile(r"^([a-z]{3,6})(\d{2})(\d{2})$")
#: A period embedded anywhere: `mer_2024-04`, `freightos_2025-12-03`.
_EMBEDDED = re.compile(r"(\d{4}-W\d{2}(?:-\d{2})?|\d{4}-\d{2}-\d{2}|\d{4}-\d{2})(?!\d)")


def period_for(stem: str, known: list[str] | None = None) -> str | None:
    """The period a source filename belongs to, or None for the root.

    `known` is the scenario's own instance period names, tried first. That is
    what makes the irregular formats work: Bank of England files are named
    `2023-August03.pdf` and ECB's `2023-Dec14.pdf`, which no numeric pattern
    matches, but both are the period name verbatim.
    """
    for p in sorted(known or [], key=len, reverse=True):
        if p in stem:
            return p
    if _CAPTURE.search(stem):
        return None
    m = _TRAILING_YYYYMM.search(stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = _PUBLISHER_CODE.match(stem)
    if m:
        return f"20{m.group(3)}-{m.group(2)}"
    m = _EMBEDDED.search(stem)
    if m:
        return m.group(1)
    return None


class SourceTree:
    """A `source/` directory addressed as if it were flat."""

    def __init__(self, root: Path, known_periods: list[str] | None = None):
        self.root = Path(root)
        self._known = list(known_periods or [])

    # -- writing -----------------------------------------------------------

    def __truediv__(self, name: str) -> Path:
        """Where an artifact called `name` belongs.

        Returns a real Path, so callers keep using `.write_bytes()`,
        `.exists()`, `shutil.copy2()` and the rest untouched. The parent
        directory is created here because every caller previously relied on a
        single `mkdir` of the flat directory.
        """
        name = str(name)
        period = period_for(Path(name).stem, self._known)
        target = self.root / period / name if period else self.root / name
        # Routing depends on the known-period list, which grows as periods are
        # added, so a file written under one list can route elsewhere under the
        # next: fred_sahm's 2026-M06.json landed at the root at download time
        # and was looked for in 2026-M06/ at format time. An existing file with
        # this name wins wherever it sits.
        if not target.exists():
            for cand in (self.root / name, *self.root.glob(f"*/{name}")):
                if cand.is_file():
                    return cand
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def mkdir(self, *_, **__) -> None:
        """No-op beyond the root: period folders are created on demand."""
        self.root.mkdir(parents=True, exist_ok=True)

    # -- reading -----------------------------------------------------------

    def glob(self, pattern: str) -> Iterator[Path]:
        """Match `pattern` against filenames anywhere in the tree.

        Scripts wrote `GT_SOURCE.glob("*.pdf")` against a flat directory. The
        files are now one level deeper, so a plain glob would return nothing —
        silently, which is the failure mode worth avoiding. Search both levels
        and sort by name so callers that relied on `sorted(...)` ordering see
        the same sequence.
        """
        if not self.root.is_dir():
            return iter(())
        seen = {}
        for p in list(self.root.glob(pattern)) + list(self.root.glob(f"*/{pattern}")):
            # Pipeline bookkeeping, not data. These used to sit in the other
            # legacy directory, so a glob for "*.json" never saw them; with one
            # tree they collide, and usda_cattle_on_feed_placements_yoy died
            # trying to parse _manifest.json as an observation.
            if p.is_file() and not p.name.startswith("_"):
                seen[p.name] = p
        return iter(sorted(seen.values(), key=lambda p: p.name))

    def iterdir(self) -> Iterator[Path]:
        """Every file in the tree, period folders flattened."""
        return self.glob("*")

    def exists(self) -> bool:
        return self.root.exists()

    def is_dir(self) -> bool:
        return self.root.is_dir()

    @property
    def parent(self) -> Path:
        return self.root.parent

    @property
    def name(self) -> str:
        return self.root.name

    def __fspath__(self) -> str:
        return str(self.root)

    def __str__(self) -> str:
        return str(self.root)

    def __repr__(self) -> str:
        return f"SourceTree({self.root!r})"
