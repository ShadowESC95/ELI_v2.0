"""Shared ELI branding assets (window icon, Freedesktop theme, Windows .ico)."""
from __future__ import annotations

import io
import os
import shutil
from pathlib import Path
from typing import Optional

ICON_NAME = "eli"
_ICON_REL_CANDIDATES = (
    "packaging/desktop/Eli_Icon.png",
    "blueprints/Eli_Icon.png",
)


def _project_root(root: Optional[Path] = None) -> Optional[Path]:
    if root is not None:
        return Path(root).expanduser().resolve()
    try:
        from eli.core.paths import project_root
        return Path(project_root())
    except Exception:
        return None


def source_icon_path(root: Optional[Path] = None) -> Optional[Path]:
    base = _project_root(root)
    if base is None:
        return None
    for rel in _ICON_REL_CANDIDATES:
        p = base / rel
        if p.is_file():
            return p
    return None


def sync_runtime_icon_copy(root: Optional[Path] = None) -> Optional[Path]:
    """Ensure blueprints/Eli_Icon.png exists for legacy path lookups."""
    base = _project_root(root)
    src = source_icon_path(base)
    if base is None or src is None:
        return None
    dst = base / "blueprints" / "Eli_Icon.png"
    if src.resolve() != dst.resolve():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return dst


def _square_png_bytes(src: Path, size: int, *, maskable: bool = False) -> bytes:
    from PIL import Image

    im = Image.open(src).convert("RGBA")
    bg = (6, 20, 31, 255) if maskable else (0, 0, 0, 0)
    pad = 0.72 if maskable else 0.88
    canvas = Image.new("RGBA", (size, size), bg)
    box = int(size * pad)
    sw, sh = im.size
    scale = min(box / max(1, sw), box / max(1, sh))
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    im = im.resize((nw, nh), Image.LANCZOS)
    canvas.alpha_composite(im, ((size - nw) // 2, (size - nh) // 2))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def write_packaged_icons(root: Optional[Path] = None) -> Path:
    """Build square PNG sizes + Eli_Icon.ico under packaging/desktop/ (release step)."""
    base = _project_root(root)
    src = source_icon_path(base)
    if base is None or src is None:
        raise FileNotFoundError("Eli_Icon.png not found under packaging/desktop or blueprints/")
    out_dir = base / "packaging" / "desktop"
    out_dir.mkdir(parents=True, exist_ok=True)
    for size in (48, 128, 256):
        (out_dir / f"eli-{size}.png").write_bytes(_square_png_bytes(src, size))
    ico_path = out_dir / "Eli_Icon.ico"
    from PIL import Image

    imgs = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        imgs.append(Image.open(io.BytesIO(_square_png_bytes(src, size))).convert("RGBA"))
    imgs[0].save(ico_path, format="ICO", sizes=[(im.width, im.height) for im in imgs], append_images=imgs[1:])
    sync_runtime_icon_copy(base)
    return ico_path


def install_linux_theme_icon(root: Optional[Path] = None) -> str:
    """Install ~/.local/share/icons/hicolor/*/apps/eli.png — returns Freedesktop icon name."""
    src = source_icon_path(root)
    if src is None:
        return ICON_NAME
    theme_base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "icons" / "hicolor"
    for size in (48, 128, 256):
        dest_dir = theme_base / f"{size}x{size}" / "apps"
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / f"{ICON_NAME}.png").write_bytes(_square_png_bytes(src, size))
    # Scalable alias for DEs that prefer it
    scalable = theme_base / "scalable" / "apps"
    scalable.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, scalable / f"{ICON_NAME}.png")
    return ICON_NAME


def prepare_launcher_icons(root: Optional[Path] = None) -> str:
    """Sync blueprints copy + install Freedesktop theme icon; return .desktop Icon= value."""
    sync_runtime_icon_copy(root)
    if os.name == "nt":
        base = _project_root(root)
        if base is None:
            return ICON_NAME
        ico = base / "packaging" / "desktop" / "Eli_Icon.ico"
        png = base / "packaging" / "desktop" / "Eli_Icon.png"
        if ico.is_file():
            return str(ico)
        if png.is_file():
            return str(png)
        return ICON_NAME
    return install_linux_theme_icon(root)


def resolve_app_icon_path() -> Optional[Path]:
    return source_icon_path()


def load_app_icon():
    from eli.gui.panels._qt import QIcon

    p = resolve_app_icon_path()
    return QIcon(str(p)) if p else None
