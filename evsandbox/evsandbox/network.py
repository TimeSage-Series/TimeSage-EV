"""Time-isolated network layer for IATA-style scenarios.

Three layers, in order:
  1. Discovery: SearXNG (local Docker, 127.0.0.1:8888) — no time_range filter
     (it only supports relative-to-now, useless for backtesting).
  2. Content: Common Crawl CDX API — the index used is selected per-call
     from `collinfo.json` based on the caller-supplied `cutoff`; captures
     are further filtered with `to=cutoff - 7 days`.
  3. Fallback: Wayback Machine — same timestamp filter.

Every call writes one row to `audit_path` (network_audit.jsonl).

This module is intentionally network-dependency-light: real HTTP calls
happen only when `TIMESAGE_SEARXNG` is set in the env. In the offline
mock path used by MockLM and unit tests, we synthesize a deterministic
"miss" result so the audit row still gets written and the chain is
exercised.

"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


_DATE_FMTS = ("%Y-%m-%d", "%Y-%m", "%Y-wk%U")


def _parse_cutoff(cutoff: str) -> datetime:
    """Accept the loose period strings we use as cutoffs and produce an
    end-of-period datetime in UTC."""
    for fmt in _DATE_FMTS:
        try:
            dt = datetime.strptime(cutoff, fmt).replace(tzinfo=timezone.utc)
            # week / month strings → end-of-period
            if fmt == "%Y-%m":
                # last day of month at 23:59
                from calendar import monthrange
                last = monthrange(dt.year, dt.month)[1]
                return dt.replace(day=last, hour=23, minute=59)
            if fmt == "%Y-wk%U":
                return dt + timedelta(days=6, hours=23, minutes=59)
            return dt.replace(hour=23, minute=59)
        except ValueError:
            continue
    # default fallback — interpret as YYYY-MM-DD-ish
    return datetime.now(timezone.utc) - timedelta(days=365)


def _cdx_cutoff_yyyymmdd(cutoff: str) -> str:
    """`cutoff - 7 days` formatted as YYYYMMDD for CDX API."""
    dt = _parse_cutoff(cutoff) - timedelta(days=7)
    return dt.strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# Audit writer
# ---------------------------------------------------------------------------

_audit_lock = threading.Lock()


def _write_audit(audit_path: Path, row: dict) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, separators=(",", ":"))
    with _audit_lock:
        with audit_path.open("a") as f:
            f.write(line + "\n")


# ---------------------------------------------------------------------------
# Discovery (SearXNG) + Content (CDX) + Fallback (Wayback)
# ---------------------------------------------------------------------------

def _searxng_endpoints() -> list[str]:
    raw = os.environ.get("TIMESAGE_SEARXNG", "")
    return [e.strip() for e in raw.split(",") if e.strip()]


def _searxng_search(query: str, max_n: int = 30) -> list[dict]:
    """Hit SearXNG /search?format=json. Returns [{title, url, content}]."""
    endpoints = _searxng_endpoints()
    if not endpoints:
        return []
    try:
        import requests                                              # noqa: WPS433
    except Exception:                                                # noqa: BLE001
        return []
    ep = random.choice(endpoints)
    try:
        r = requests.get(f"{ep}/search",
                         params={"q": query, "format": "json", "safesearch": 1},
                         timeout=10)
        r.raise_for_status()
        data = r.json()
        return list(data.get("results") or [])[:max_n]
    except Exception:                                                # noqa: BLE001
        return []


_cc_catalog_cache: Optional[list[dict]] = None
_cc_catalog_lock = threading.Lock()
_CC_COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"


def _cc_index_catalog() -> list[dict]:
    """Fetch (and cache process-wide) the Common Crawl index catalog.

    `collinfo.json` is sorted newest-first; each entry has `from`, `to`,
    and `cdx-api`. Cached for the lifetime of the process — the catalog
    only changes when CC publishes a new monthly crawl.
    """
    global _cc_catalog_cache
    if _cc_catalog_cache is not None:
        return _cc_catalog_cache
    with _cc_catalog_lock:
        if _cc_catalog_cache is not None:
            return _cc_catalog_cache
        try:
            import requests                                          # noqa: WPS433
            r = requests.get(_CC_COLLINFO_URL, timeout=8)
            r.raise_for_status()
            _cc_catalog_cache = list(r.json() or [])
        except Exception:                                            # noqa: BLE001
            _cc_catalog_cache = []
    return _cc_catalog_cache


def _cdx_indexes_for(cutoff_yyyymmdd: str, max_n: int = 3) -> list[str]:
    """Pick the newest CC-MAIN indexes whose crawl `from` date is ≤ cutoff.

    The CDX API itself filters captures via `to=cutoff_yyyymmdd`, so any
    index that *started* before the cutoff is safe to query — it just may
    contain post-cutoff captures that get filtered out server-side.
    """
    out: list[str] = []
    for c in _cc_index_catalog():
        frm = (c.get("from") or "")[:10].replace("-", "")
        api = c.get("cdx-api")
        if not (frm and api):
            continue
        if frm <= cutoff_yyyymmdd:
            out.append(api)
            if len(out) >= max_n:
                break
    return out


def _cdx_lookup(url: str, cutoff_yyyymmdd: str,
                indexes: Optional[list[str]] = None) -> Optional[dict]:
    """Common Crawl CDX. Returns the latest capture with timestamp <= cutoff.

    Tries each index in `indexes` (newest-first) until one returns a hit.
    If `indexes` is None, derives the list from `cutoff_yyyymmdd`.
    """
    try:
        import requests                                              # noqa: WPS433
    except Exception:                                                # noqa: BLE001
        return None
    if indexes is None:
        indexes = _cdx_indexes_for(cutoff_yyyymmdd)
    for api in indexes:
        try:
            r = requests.get(api, params={
                "url": url, "to": cutoff_yyyymmdd, "output": "json", "limit": 1,
            }, timeout=8)
            if r.status_code != 200 or not r.text.strip():
                continue
            rec = json.loads(r.text.splitlines()[0])
            return {"url": rec.get("url", url), "timestamp": rec.get("timestamp"),
                    "snippet": "", "source": "cdx"}
        except Exception:                                            # noqa: BLE001
            continue
    return None


def _wayback_lookup(url: str, cutoff_yyyymmdd: str) -> Optional[dict]:
    try:
        import requests                                              # noqa: WPS433
    except Exception:                                                # noqa: BLE001
        return None
    try:
        r = requests.get("https://archive.org/wayback/available",
                         params={"url": url, "timestamp": cutoff_yyyymmdd},
                         timeout=8)
        r.raise_for_status()
        closest = (r.json() or {}).get("archived_snapshots", {}).get("closest")
        if not closest:
            return None
        ts = closest.get("timestamp", "")
        if not ts or ts > cutoff_yyyymmdd:
            return None
        return {"url": closest.get("url", url), "timestamp": ts,
                "snippet": "", "source": "wayback"}
    except Exception:                                                # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def search_with_isolation(*, query: str, n: int, cutoff: str,
                          audit_path: Optional[Path] = None) -> list[dict]:
    """Run the three-layer pipeline and write one audit row.

    Offline mode (no SearXNG endpoint) writes a "miss" audit row and
    returns an empty list; this lets unit tests exercise the chain.
    """
    cutoff_ymd = _cdx_cutoff_yyyymmdd(cutoff)
    raw = _searxng_search(query, max_n=max(n * 3, 9))
    cdx_indexes = _cdx_indexes_for(cutoff_ymd)

    results: list[dict] = []
    cdx_hits = wb_hits = misses = 0
    stamps: list[str] = []
    for r in raw:
        url = r.get("url", "")
        if not url:
            continue
        archived = _cdx_lookup(url, cutoff_ymd, indexes=cdx_indexes)
        if archived:
            cdx_hits += 1
            stamps.append(archived["timestamp"])
            results.append({
                "url": url, "archived_at": archived["timestamp"],
                "html_snippet": r.get("content", "")[:600],
                "source": "cdx",
            })
        else:
            wb = _wayback_lookup(url, cutoff_ymd)
            if wb:
                wb_hits += 1
                stamps.append(wb["timestamp"])
                results.append({
                    "url": url, "archived_at": wb["timestamp"],
                    "html_snippet": r.get("content", "")[:600],
                    "source": "wayback",
                })
            else:
                misses += 1
        if len(results) >= n:
            break

    if audit_path is not None:
        _write_audit(audit_path, {
            "ts":         datetime.now(timezone.utc).isoformat(),
            "query":      query,
            "cutoff_ymd": cutoff_ymd,
            "searxng_n":  len(raw),
            "cdx_indexes": [api.rsplit("/", 1)[-1] for api in cdx_indexes],
            "cdx_hits":   cdx_hits,
            "wayback_hits": wb_hits,
            "misses":     misses,
            "archived_timestamps": stamps,
        })
    return results


# ---------------------------------------------------------------------------
# SearXNG health check (used by `agent-eval searxng healthcheck`)
# ---------------------------------------------------------------------------

def searxng_healthcheck() -> dict:
    """Probe each configured SearXNG endpoint. Returns per-endpoint status."""
    out = {"endpoints": [], "healthy": True}
    for ep in _searxng_endpoints():
        rec: dict = {"endpoint": ep}
        t0 = time.monotonic()
        try:
            import requests                                          # noqa: WPS433
            r = requests.get(f"{ep}/search",
                             params={"q": "site:reuters.com aviation",
                                     "format": "json"},
                             timeout=6)
            rec["status"] = r.status_code
            rec["latency_ms"] = int((time.monotonic() - t0) * 1000)
            rec["n_results"] = len((r.json() or {}).get("results") or [])
            rec["ok"] = r.status_code == 200 and rec["n_results"] > 0
        except Exception as exc:                                     # noqa: BLE001
            rec["ok"] = False
            rec["error"] = repr(exc)[:200]
        out["endpoints"].append(rec)
        if not rec.get("ok"):
            out["healthy"] = False
    return out
