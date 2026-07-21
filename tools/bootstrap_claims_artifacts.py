#!/usr/bin/env python3
"""Bootstrap artifacts the claims suite expects on a fresh clone.

Safe to run before pytest tests/claims/ or in CI — idempotent, never raises.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MIN_CAPS = 200
_EXPECTED_DBS = (
    "user.sqlite3",
    "agent.sqlite3",
    "system_index.sqlite3",
    "coding_memory.sqlite3",
)


def _ensure_db_stores() -> bool:
    """Mirror install.sh: seed blank templates, then init full schema for claims."""
    artifact_dir = ROOT / "artifacts" / "db"
    template_dir = ROOT / "config" / "templates" / "db"
    try:
        if template_dir.is_dir():
            artifact_dir.mkdir(parents=True, exist_ok=True)
            if not any(artifact_dir.glob("*.sqlite3")):
                for src in template_dir.glob("*.sqlite3"):
                    shutil.copy2(src, artifact_dir / src.name)
        from eli.core.init_data import init_all_data

        init_all_data()
        missing = [n for n in _EXPECTED_DBS if not (artifact_dir / n).exists()]
        if missing:
            print(f"[WARN] DB stores missing after init: {', '.join(missing)}", file=sys.stderr)
            return False
        print(f"[OK] database stores ({len(_EXPECTED_DBS)} blank SQLite files)")
        return True
    except Exception as e:
        print(f"[WARN] DB bootstrap skipped: {e}", file=sys.stderr)
        return False


def _manifest_is_valid(path: Path) -> bool:
    """A tracked manifest with a plausible capability count is good enough — no need
    to regenerate (regeneration rewrites `generated_at` and dirties the working tree
    on every claims-suite run)."""
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("total") or 0) >= MIN_CAPS
    except Exception:
        return False


def main() -> int:
    manifest = ROOT / "capability_manifest.json"
    ok = True

    if not _ensure_db_stores():
        ok = False

    # Only (re)generate the manifest when it's missing or stale on a fresh clone.
    # A valid, tracked manifest is left untouched so running the suite never dirties git.
    if _manifest_is_valid(manifest):
        print("[OK] capability manifest present (kept as-is)")
    else:
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

    # capability_inventory.generated.json — bundled introspection data (the engine
    # fallback at engine.py + capability_sync's baseline). It is written by
    # CapabilitySync, NOT by update_capability_manifest (whose docstring wrongly
    # claims it), so without generating it here a fresh CI clone would ship the
    # AppImage WITHOUT it (ELI.spec only WARNS on its absence, it doesn't fail).
    # Produce it now so the same CI PyInstaller step bundles a complete set.
    inventory = ROOT / "capability_inventory.generated.json"
    if not inventory.is_file():
        try:
            from eli.runtime.capability_sync import CapabilitySync
            CapabilitySync(repo_root=ROOT).run()
        except Exception as e:
            print(f"[WARN] capability inventory generation skipped: {e}", file=sys.stderr)
    if inventory.is_file():
        print("[OK] capability inventory present")
    else:
        print("[ERR] capability_inventory.generated.json missing after bootstrap", file=sys.stderr)
        ok = False

    bp = ROOT / "blueprints"
    pdfs = list(bp.glob("*.pdf")) if bp.is_dir() else []
    if not pdfs:
        print("[WARN] no blueprints/*.pdf — ship PDF docs for reference", file=sys.stderr)
        ok = False
    else:
        print(f"[OK] blueprints ({len(pdfs)} PDFs in git; markdown stays local)")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
