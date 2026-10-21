"""Terminal progress lines for the evsandbox CLI.

Colour and icons are used only when stdout is a terminal, so logs and pipes
get plain `key=value` text; NO_COLOR (https://no-color.org) turns them off,
FORCE_COLOR turns them on.
"""
from __future__ import annotations

import os
import sys

#: (label, score_record key, colour of its dot and label), in display order.
AXES = (("accuracy",     "keypoint_accuracy",   "cyan"),
        ("faithfulness", "report_faithfulness", "magenta"),
        ("coverage",     "keypoint_coverage",   "blue"),
        ("quality",      "report_quality",      "yellow"))
DOT = "●"

_CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33",
          "blue": "34", "magenta": "35", "cyan": "36"}


def _color_on() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return bool(os.environ.get("FORCE_COLOR")) or sys.stdout.isatty()


def paint(text: str, *styles: str) -> str:
    if not styles or not _color_on():
        return text
    return f"\033[{';'.join(_CODES[s] for s in styles)}m{text}\033[0m"


def _status(status: str) -> str:
    color = {"ok": "green", "incomplete": "yellow", "agent_timeout": "yellow"}.get(status, "red")
    if not _color_on():
        return f"status={status}"
    # fixed width keeps the score columns aligned across ok / incomplete / crash
    return paint(DOT, color) + " " + paint(f"{status:<13}", color, "bold")


def _value(axis: dict | None) -> str:
    if not axis:
        return paint(f"{'—':>5}", "dim")
    value = axis.get("value")
    if value is None:
        # judge_unavailable / skipped; the plain-text form names which
        return paint(f"{'n/a':>5}", "magenta", "bold")
    color = "green" if value >= 80 else "yellow" if value >= 50 else "red"
    return paint(f"{value:5.1f}", color, "bold")


def _axis(name: str, axis: dict | None, label_color: str) -> str:
    if not _color_on():
        value = axis.get("value") if axis else None
        shown = f"{value:.1f}" if value is not None else ((axis or {}).get("status") or "—")
        return f"{name}={shown}"
    return f"{paint(DOT, label_color)} {paint(name, label_color)} {_value(axis)}"


def _tokens(usage: dict | None) -> str:
    known = bool(usage) and usage.get("input_tokens") is not None
    inp = (usage or {}).get("input_tokens") or 0
    out = (usage or {}).get("output_tokens") or 0
    if not _color_on():
        return f"tokens={inp + out:,} (in {inp:,} / out {out:,})" if known else "tokens=—"
    if not known:
        return paint("tokens", "dim") + " " + paint("—", "dim")
    return (paint("tokens", "dim") + " " + paint(f"{inp + out:,}", "bold")
            + paint(f" (in {inp:,} / out {out:,})", "dim"))


def turn_line(rec: dict, prefix: str = "") -> str:
    """One line per episode period: turn, period, status, wall time, the four
    axis scores and the period's token use."""
    scores = (rec.get("score") or {}).get("scores") or {}
    turn = f"turn {rec.get('turn', '?')}/{rec.get('n_turns', '?')}"
    wall = rec.get("wall_ms", 0)
    if _color_on():
        head = paint(turn, "bold")
        wall_s = paint("wall", "dim") + " " + f"{wall / 1000:5.1f}s"
    else:
        head, wall_s = turn, f"wall={wall}ms"
    parts = [f"{prefix}{head}", paint(f"{rec.get('period', '?'):>9}", "bold"),
             _status(rec.get("status") or "?"), wall_s,
             *(_axis(name, scores.get(key), color) for name, key, color in AXES),
             _tokens(rec.get("usage"))]
    return "  ".join(parts)


def episode_summary(turns: list[dict]) -> str:
    n_ok = sum(1 for t in turns if t.get("status") == "ok")
    tok = sum((t.get("usage") or {}).get("input_tokens", 0) or 0 for t in turns) + \
          sum((t.get("usage") or {}).get("output_tokens", 0) or 0 for t in turns)
    ok = paint(f"{n_ok}/{len(turns)} ok", "green" if n_ok == len(turns) else "yellow", "bold")
    if not _color_on():
        return f"episode complete: {ok} across {len(turns)} turns" + \
               (f"  ·  tokens {tok:,}" if tok else "")
    mark = paint(DOT, "green" if n_ok == len(turns) else "yellow")
    return f"{mark} episode complete: {ok} across {len(turns)} turns" + \
           (paint("  ·  tokens ", "dim") + paint(f"{tok:,}", "bold") if tok else "")
