"""Shared ELI branding assets (window icon, etc.)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def resolve_app_icon_path() -> Optional[Path]:
    try:
        from eli.core.paths import project_root
        root = Path(project_root())
    except Exception:
        return None
    for rel in ("packaging/desktop/Eli_Icon.png", "blueprints/Eli_Icon.png"):
        p = root / rel
        if p.is_file():
            return p
    return None


def load_app_icon():
    from eli.gui.panels._qt import QIcon

    p = resolve_app_icon_path()
    return QIcon(str(p)) if p else None
