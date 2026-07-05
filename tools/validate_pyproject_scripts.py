#!/usr/bin/env python3
"""CI guard: project.scripts values must be strings (catches eli-v2.0 TOML nesting)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eli.core.toml_util import load_toml  # noqa: E402


def main() -> int:
    scripts = (load_toml(ROOT / "pyproject.toml").get("project") or {}).get("scripts") or {}
    bad = {k: v for k, v in scripts.items() if not isinstance(v, str)}
    if bad:
        print(f"project.scripts must be strings: {bad}", file=sys.stderr)
        return 1
    print("pyproject scripts OK:", list(scripts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
