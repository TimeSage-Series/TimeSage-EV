#!/usr/bin/env python3
"""Render per-instance question.md files from the scenario template.

Current questions are checked in. Use this entry point when refreshing the
scenario after editing environment/session_brief.md or question_template.md.
"""

from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    print(f"Rendered questions are checked in under {root / 'instances'}")


if __name__ == "__main__":
    main()
