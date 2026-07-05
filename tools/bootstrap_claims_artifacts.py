#!/usr/bin/env python3
"""Bootstrap artifacts the claims suite expects on a fresh clone.

Safe to run before pytest tests/claims/ or in CI — idempotent, never raises.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MIN_CAPS = 200


def main() -> int:
    manifest = ROOT / "capability_manifest.json"
    ok = True

    try:
        from eli.tools.registry.capability_updater import update_capability_manifest
        r = update_capability_manifest()
        if not r.get("ok"):
            print(f"[WARN] manifest refresh: {r}", file=sys.stderr)
            ok = False
        else:
            print(f"[OK] capability manifest ({r.get('total', '?')} capabilities)")
    except Exception as e:
        print(f"[WARN] manifest refresh skipped: {e}", file=sys.stderr)

    if manifest.is_file():
        try:
            total = int(json.loads(manifest.read_text(encoding="utf-8")).get("total") or 0)
            if total < MIN_CAPS:
                print(f"[WARN] manifest total {total} < {MIN_CAPS}", file=sys.stderr)
                ok = False
        except Exception as e:
            print(f"[WARN] manifest unreadable: {e}", file=sys.stderr)
            ok = False
    else:
        print("[ERR] capability_manifest.json missing after bootstrap", file=sys.stderr)
        ok = False

    bp = ROOT / "blueprints"
    if not bp.is_dir() or not any(bp.glob("*.md")):
        print("[WARN] blueprints/*.md missing — claims blueprint refs will fail", file=sys.stderr)
        ok = False
    else:
        print(f"[OK] blueprints ({len(list(bp.glob('*.md')))} docs)")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
