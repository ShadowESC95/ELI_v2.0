"""Install-time platform detection — routes GUI, headless, and Android profiles."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
import platform
import sys
from typing import Optional


class InstallProfile(str, Enum):
    """Which installer path ELI should use on this host."""

    DESKTOP = "desktop"              # Full GUI + desktop app (Linux/macOS/Windows x64)
    ANDROID_HEADLESS = "android"     # Termux / Android — CPU headless runtime only
    WINDOWS_WOA = "windows_woa"      # Windows on ARM (Snapdragon) — CPU/Vulkan experimental


@dataclass(frozen=True)
class PlatformInfo:
    profile: InstallProfile
    os_name: str
    machine: str
    label: str
    gpu_note: str
    launch_command: tuple[str, ...]
    supports_gui: bool
    supports_desktop_app: bool


def _machine() -> str:
    return (platform.machine() or "").lower()


def is_android_headless() -> bool:
    try:
        from eli.utils.platform_compat import is_android
        return bool(is_android())
    except Exception:
        return False


def is_windows_on_arm() -> bool:
    return sys.platform == "win32" and _machine() in ("arm64", "aarch64")


def detect_install_profile() -> InstallProfile:
    if is_android_headless():
        return InstallProfile.ANDROID_HEADLESS
    if is_windows_on_arm():
        return InstallProfile.WINDOWS_WOA
    return InstallProfile.DESKTOP


def get_platform_info() -> PlatformInfo:
    profile = detect_install_profile()
    machine = _machine() or "unknown"

    if profile == InstallProfile.ANDROID_HEADLESS:
        return PlatformInfo(
            profile=profile,
            os_name="android",
            machine=machine,
            label="Android / Termux (headless)",
            gpu_note="CPU inference only — no CUDA, no desktop GPU offload pack.",
            launch_command=("python", "-m", "eli.cli.headless"),
            supports_gui=False,
            supports_desktop_app=False,
        )

    if profile == InstallProfile.WINDOWS_WOA:
        return PlatformInfo(
            profile=profile,
            os_name="windows",
            machine=machine,
            label="Windows on ARM (Snapdragon)",
            gpu_note=(
                "Qualcomm Adreno unified memory — Vulkan offload experimental; "
                "prebuilt CUDA wheels unavailable on arm64."
            ),
            launch_command=("python", "-m", "eli"),
            supports_gui=True,
            supports_desktop_app=True,
        )

    os_name = (
        "windows" if sys.platform == "win32"
        else "macos" if sys.platform == "darwin"
        else "linux"
    )
    return PlatformInfo(
        profile=profile,
        os_name=os_name,
        machine=machine,
        label=f"{os_name} ({machine})",
        gpu_note="Full GPU detection — NVIDIA, AMD, Intel iGPU, Qualcomm Adreno, Apple Metal.",
        launch_command=("python", "-m", "eli"),
        supports_gui=True,
        supports_desktop_app=True,
    )


def install_script_for_profile(root, profile: Optional[InstallProfile] = None):
    """Return (script_path, argv_prefix) for the active install profile."""
    from pathlib import Path

    root = Path(root)
    prof = profile or detect_install_profile()

    if prof == InstallProfile.ANDROID_HEADLESS:
        script = root / "scripts" / "install_android.sh"
        if not script.is_file():
            raise FileNotFoundError(f"scripts/install_android.sh not found under {root}")
        return script, ["bash", str(script)]

    if sys.platform == "win32":
        script = root / "install.ps1"
        if not script.is_file():
            raise FileNotFoundError(f"install.ps1 not found under {root}")
        import shutil
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if not pwsh:
            raise RuntimeError("PowerShell not found — cannot run install.ps1")
        return script, [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Yes", "-AutoModel"]

    script = root / "install.sh"
    if not script.is_file():
        raise FileNotFoundError(f"install.sh not found under {root}")
    argv = ["bash", str(script), "--yes"]
    if os.environ.get("ELI_INSTALL_CPU_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}:
        argv.append("--cpu-only")
    argv.append("--auto-model")
    return script, argv
