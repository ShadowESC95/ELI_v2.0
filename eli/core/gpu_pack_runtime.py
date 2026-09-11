"""Activate the optional GPU pack before llama_cpp is imported (AppImage/portable)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from eli.utils.log import get_logger

log = get_logger(__name__)


def _import_gpu_pack_module():
    try:
        import eli_gpu_pack
        return eli_gpu_pack
    except ImportError:
        log.debug("eli_gpu_pack not importable as frozen module", exc_info=True)
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass) / "packaging" / "pyinstaller")
    try:
        from eli.core.paths import project_root
        candidates.append(Path(project_root()) / "packaging" / "pyinstaller")
    except Exception:
        log.debug("project_root unavailable for gpu pack import path", exc_info=True)
    for base in candidates:
        if (base / "eli_gpu_pack.py").is_file():
            sys.path.insert(0, str(base))
            import eli_gpu_pack
            return eli_gpu_pack
    raise ImportError("eli_gpu_pack not found")


def try_activate_gpu_pack(*, verify: bool = True) -> bool:
    """Make a verified GPU pack active in this process. Safe before llama_cpp import."""
    if os.environ.get("ELI_DISABLE_GPU_PACK", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    try:
        from eli.core.paths import project_root
        root = Path(project_root())
        dest = root / "runtime" / "gpu"
        marker = root / "runtime" / ".gpu_choice"
        if marker.is_file():
            choice = marker.read_text(encoding="utf-8", errors="replace").strip()
            if choice.startswith("cpu"):
                return False
        if not (dest / "llama_cpp").is_dir():
            return False
        gp = _import_gpu_pack_module()
        if not gp.gpu_pack_operational(dest) and not (dest / ".gpu_pack_ok").is_file():
            return False
        ok = bool(gp.activate_gpu_pack_runtime(dest, verify=verify))
        if ok:
            log.info("GPU pack active for this session (%s)", dest)
        else:
            log.debug("GPU pack present but could not activate in this process")
        return ok
    except Exception:
        log.debug("GPU pack activation skipped", exc_info=True)
        return False


def trust_vulkan_igpu_offload() -> bool:
    """True when a verified Vulkan pack is present on a shared-memory iGPU.

    ``llama_supports_gpu_offload()`` often returns False in AppImage on Iris Xe
    even after a successful pack install; callers may still attempt a few GPU
    layers instead of forcing CPU-only.
    """
    try:
        from eli.core.paths import project_root
        root = Path(project_root())
        dest = root / "runtime" / "gpu"
        if not (dest / ".gpu_pack_ok").is_file():
            return False
        gp = _import_gpu_pack_module()
        return bool(gp._relax_offload_verify(dest))
    except Exception:
        log.debug("trust_vulkan_igpu_offload probe failed", exc_info=True)
        return False
