"""Runtime media capability probe — what works on THIS machine/OS.

Used for honest user feedback ("mpv missing", "playerctl unavailable") and
self-diagnostics. Safe to call on any OS; never raises.
"""
from __future__ import annotations

import os
import shutil
from typing import Any

from eli.utils import platform_compat as pc


def _which(name: str) -> bool:
    return bool(shutil.which(name))


def _browser_candidates() -> list[str]:
    found: list[str] = []
    if pc.LINUX and not pc.ANDROID:
        for name in (
            "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
            "brave-browser", "microsoft-edge", "firefox", "opera", "vivaldi",
        ):
            if _which(name):
                found.append(name)
        for path in ("/snap/bin/chromium", "/snap/bin/firefox"):
            if os.path.isfile(path) and os.access(path, os.X_OK):
                base = os.path.basename(path)
                if base not in found:
                    found.append(base)
    elif pc.MACOS:
        found = list(pc.MACOS_APP_CANDIDATES.get("browser", ()))
    elif pc.WINDOWS:
        for name in ("chrome", "msedge", "firefox", "brave"):
            if _which(name):
                found.append(name)
    return found


def detect_media_capabilities() -> dict[str, Any]:
    """Return a snapshot of media-related tools on the host."""
    browsers = _browser_candidates()
    override = (os.environ.get("ELI_BROWSER") or "").strip()
    vol_backend = None
    for tool in ("wpctl", "pactl", "amixer"):
        if _which(tool):
            vol_backend = tool
            break
    return {
        "platform": pc.normalize_platform(),
        "browser_override": override or None,
        "browsers_found": browsers,
        "browser_available": bool(override or browsers or pc.ANDROID),
        "mpv": _which("mpv"),
        "yt_dlp": _which("yt-dlp"),
        "playerctl": _which("playerctl"),
        "spotify_cli": _which("spotify") or _which("flatpak") or _which("snap"),
        "volume_backend": vol_backend,
        "wmctrl": _which("wmctrl"),
        "xdotool": _which("xdotool"),
        "ydotool": _which("ydotool"),
        "youtube_mpv_ready": _which("mpv") and _which("yt-dlp"),
        "youtube_direct_note": (
            "YouTube background audio needs mpv + yt-dlp installed and on PATH."
            if not (_which("mpv") and _which("yt-dlp"))
            else None
        ),
    }


def detect_hardware_capabilities() -> dict[str, Any]:
    """GPU/RAM snapshot for startup diagnostics. Never raises."""
    out: dict[str, Any] = {"ok": False}
    try:
        from eli.core.hardware_profile import detect_hardware
        hw = detect_hardware()
        out = {
            "ok": True,
            "cpu_cores": hw.get("cpu_cores"),
            "ram_gb": hw.get("ram_gb"),
            "gpus": hw.get("gpus") or [],
            "primary_gpu": (hw.get("gpus") or [{}])[0].get("name") if hw.get("gpus") else None,
            "vram_mb": (hw.get("gpus") or [{}])[0].get("vram_mb") if hw.get("gpus") else None,
        }
    except Exception:
        pass
    return out


def platform_capability_report(*, verbose: bool = False) -> str:
    """Human-readable startup report of what works on THIS machine."""
    media = detect_media_capabilities()
    hw = detect_hardware_capabilities()
    lines = [
        f"Platform: {media['platform']}",
    ]
    if hw.get("ok"):
        gpu = hw.get("primary_gpu") or "CPU-only"
        vram = hw.get("vram_mb")
        ram = hw.get("ram_gb")
        lines.append(f"Hardware: {gpu}" + (f", {vram} MiB VRAM" if vram else "") +
                     (f", {ram:.0f} GB RAM" if isinstance(ram, (int, float)) else ""))
    yt = "ready" if media["youtube_mpv_ready"] else "browser-only (install mpv + yt-dlp for background audio)"
    lines.append(f"YouTube: {yt}")
    if media["browsers_found"]:
        lines.append(f"Browsers: {', '.join(media['browsers_found'][:4])}")
    elif media["browser_override"]:
        lines.append(f"Browser: {media['browser_override']} (ELI_BROWSER)")
    else:
        lines.append("Browsers: OS default")
    transport = "playerctl" if media["playerctl"] else (
        "AppleScript" if media["platform"] == "macos" else
        "media-keys" if media["platform"] == "windows" else "limited"
    )
    lines.append(f"Media transport: {transport}")
    if media.get("volume_backend"):
        lines.append(f"Volume: {media['volume_backend']}")
    if verbose:
        wc = []
        if media.get("wmctrl"):
            wc.append("wmctrl")
        if media.get("xdotool"):
            wc.append("xdotool")
        if media.get("ydotool"):
            wc.append("ydotool")
        if wc:
            lines.append(f"Window control: {', '.join(wc)}")
        if media.get("youtube_direct_note"):
            lines.append(f"Note: {media['youtube_direct_note']}")
    return "\n".join(lines)


def media_capability_summary() -> str:
    """One-line human summary for status/self-test."""
    c = detect_media_capabilities()
    parts = [f"platform={c['platform']}"]
    if c["youtube_mpv_ready"]:
        parts.append("youtube-mpv=ready")
    elif c["mpv"] or c["yt_dlp"]:
        parts.append("youtube-mpv=partial")
    else:
        parts.append("youtube-mpv=browser-only")
    if c["playerctl"]:
        parts.append("transport=playerctl")
    elif pc.MACOS:
        parts.append("transport=applescript")
    elif pc.WINDOWS:
        parts.append("transport=media-keys")
    else:
        parts.append("transport=limited")
    if c["browser_override"]:
        parts.append(f"browser={c['browser_override'].split()[0]}")
    elif c["browsers_found"]:
        parts.append(f"browser={c['browsers_found'][0]}")
    else:
        parts.append("browser=default")
    return "; ".join(parts)
