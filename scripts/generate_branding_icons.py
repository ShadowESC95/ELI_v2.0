#!/usr/bin/env python3
"""Generate square launcher PNGs + Eli_Icon.ico from packaging/desktop/Eli_Icon.png."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eli.gui.branding import write_packaged_icons


def main() -> int:
    try:
        out = write_packaged_icons(ROOT)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"[OK] branding icons → {out.parent}/ (eli-48/128/256.png, Eli_Icon.ico)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
