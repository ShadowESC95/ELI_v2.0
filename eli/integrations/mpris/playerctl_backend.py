"""
MPRIS2 / playerctl media control backend for ELI.

Supports:
  - Spotify (desktop app)       — via playerctl, stop→pause workaround
  - VLC, MPV                    — full stop/play/pause/next/prev
  - Browser-based players       — Firefox/Chromium via MPRIS2 extension
  - System volume               — pactl (PulseAudio/PipeWire) with amixer fallback
  - Mute / unmute               — pactl toggle

Player priority (auto-select):
  configured/default player → active player → first available player

Requirements:
  - playerctl        (sudo apt install playerctl)
  - pactl            (usually pre-installed with PulseAudio/PipeWire)
  - amixer           (fallback, sudo apt install alsa-utils)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from eli.utils import platform_compat as platform


# ──────────────────────────────────────────────────────────────
# Internal subprocess helpers
# ──────────────────────────────────────────────────────────────

def _run(argv: List[str], timeout: int = 8, input_bytes: Optional[bytes] = None) -> Tuple[bool, str, str]:
    """
    Run a subprocess.
    Returns (ok: bool, stdout: str, stderr: str).
    Never raises — all exceptions → (False, "", error_msg).
    """
    try:
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            input=input_bytes.decode("utf-8") if input_bytes else None,
        )
        return (p.returncode == 0), p.stdout.strip(), p.stderr.strip()
    except FileNotFoundError:
        return False, "", f"Command not found: {argv[0]}"
    except subprocess.TimeoutExpired:
        return False, "", f"Timeout: {' '.join(argv)}"
    except Exception as e:
        return False, "", str(e)


def _has(cmd: str) -> bool:
    """Return True if command is on PATH."""
    return shutil.which(cmd) is not None


def _ok(msg: str) -> Dict[str, Any]:
    return {"ok": True, "content": msg, "response": msg}


def _err(msg: str, **kw) -> Dict[str, Any]:
    return {"ok": False, "error": msg, "content": msg, "response": msg, **kw}


# ──────────────────────────────────────────────────────────────
# Player discovery
# ──────────────────────────────────────────────────────────────

PLAYER_PRIORITY = [
    "spotify", "Spotify",
    "vlc", "VLC",
    "mpv",
    "firefox", "Firefox",
    "chromium", "Chromium",
    "chrome",
]

# Players that do NOT support MPRIS2 'stop' (only pause)
PAUSE_ONLY_PLAYERS = {"spotify"}

PLAYER_KIND_TERMS = {
    "browser": ("browser", "tab", "page", "video"),
    "youtube": ("youtube", "you tube", "yt", "youtube.com"),
    "netflix": ("netflix", "netflix.com"),
    "primevideo": ("primevideo", "prime video", "amazon prime", "primevideo.com"),
    "firefox": ("firefox",),
    "chrome": ("chrome", "chromium", "brave"),
    "chromium": ("chromium", "chrome"),
    "spotify": ("spotify",),
    "vlc": ("vlc",),
    "mpv": ("mpv",),
}


def list_players() -> List[str]:
    """
    List all currently running MPRIS2 players.
    Returns [] if playerctl is not installed or no players running.
    """
    if not _has("playerctl"):
        return []
    ok, out, _ = _run(["playerctl", "--list-all"])
    if not ok or not out:
        return []
    return [p.strip() for p in out.splitlines() if p.strip()]


def _metadata(player: str, key: str) -> str:
    ok, out, _ = _run(["playerctl", "-p", player, "metadata", key], timeout=3)
    return out if ok else ""


def get_player_info(player: str) -> Dict[str, Any]:
    _, status, _ = _run(["playerctl", "-p", player, "status"], timeout=3)
    fields = {
        "title": _metadata(player, "xesam:title") or _metadata(player, "title"),
        "artist": _metadata(player, "xesam:artist") or _metadata(player, "artist"),
        "album": _metadata(player, "xesam:album") or _metadata(player, "album"),
        "url": _metadata(player, "xesam:url"),
        "identity": _metadata(player, "mpris:identity"),
        "desktop_entry": _metadata(player, "mpris:desktopEntry"),
    }
    return {
        "player": player,
        "status": (status or "unknown").strip().lower(),
        **fields,
    }


def list_player_infos() -> List[Dict[str, Any]]:
    return [get_player_info(p) for p in list_players()]


def _target_terms(target: Optional[str]) -> List[str]:
    if not target:
        return []
    t = target.strip().lower().replace("_", " ").replace("-", " ")
    terms = {t}
    compact = t.replace(" ", "")
    if compact:
        terms.add(compact)
    for key, aliases in PLAYER_KIND_TERMS.items():
        alias_set = {key, *aliases}
        alias_set |= {a.replace(" ", "") for a in alias_set}
        if t in alias_set or compact in alias_set:
            terms.update(alias_set)
            break
    return sorted(terms, key=len, reverse=True)


def _info_haystack(info: Dict[str, Any]) -> str:
    return " ".join(str(info.get(k) or "") for k in (
        "player", "status", "title", "artist", "album", "url",
        "identity", "desktop_entry",
    )).lower()


def _status_rank(status: str, command: Optional[str]) -> int:
    s = (status or "").lower()
    c = (command or "").lower()
    if c in {"pause", "stop"}:
        return 0 if s == "playing" else 1 if s == "paused" else 2
    if c in {"play", "play-pause"}:
        return 0 if s == "paused" else 1 if s == "playing" else 2
    return 0 if s == "playing" else 1 if s == "paused" else 2


def resolve_player_target(target: Optional[str] = None, command: Optional[str] = None) -> Optional[str]:
    """Resolve an arbitrary user target against live MPRIS player metadata."""
    infos = list_player_infos()
    if not infos:
        return None

    terms = _target_terms(target)
    if terms:
        matches = [
            info for info in infos
            if any(term and term in _info_haystack(info) for term in terms)
        ]
        if matches:
            matches.sort(key=lambda i: (
                _status_rank(str(i.get("status")), command),
                _priority_rank(str(i.get("player", ""))),
            ))
            return str(matches[0]["player"])

    # Explicit browser target means any browser MPRIS player.
    if (target or "").strip().lower() in {"browser", "tab", "video", "youtube", "netflix", "primevideo"}:
        browsers = [
            info for info in infos
            if any(str(info.get("player", "")).lower().startswith(b) for b in ("firefox", "chrome", "chromium", "brave"))
        ]
        if browsers:
            browsers.sort(key=lambda i: _status_rank(str(i.get("status")), command))
            return str(browsers[0]["player"])

    return None


def _priority_rank(player: str) -> int:
    pl = player.lower()
    for idx, name in enumerate(PLAYER_PRIORITY):
        if pl.startswith(name.lower()):
            return idx
    return 999


def get_active_player(prefer: Optional[str] = None, command: Optional[str] = None) -> Optional[str]:
    """
    Return the best player to control right now.
    Priority: prefer > env ELI_MEDIA_PLAYER > PLAYER_PRIORITY > first available.
    """
    players = list_players()
    if not players:
        return None

    target = prefer or os.environ.get("ELI_MEDIA_PLAYER", "")
    if target:
        resolved = resolve_player_target(target, command=command)
        if resolved:
            return resolved
        if prefer:
            return None

    infos = list_player_infos()
    if infos:
        infos.sort(key=lambda i: (_status_rank(str(i.get("status")), command), _priority_rank(str(i.get("player")))))
        return str(infos[0]["player"])

    return players[0]


def _is_pause_only(player: str) -> bool:
    return any(player.lower().startswith(name) for name in PAUSE_ONLY_PLAYERS)


# ──────────────────────────────────────────────────────────────
# Status / metadata
# ──────────────────────────────────────────────────────────────

def get_player_status(player: Optional[str] = None) -> Dict[str, Any]:
    """
    Return current playback status and track info.
    """
    if not _has("playerctl"):
        if not platform.LINUX:
            return _err("MPRIS/playerctl media status is Linux-only on this backend")
        return _err("playerctl not installed — run: sudo apt install playerctl")

    if player:
        p = resolve_player_target(player, command="status")
    else:
        p = get_active_player(command="status")
    if not p:
        suffix = f" matching '{player}'" if player else ""
        return _err(f"No media player{suffix} is currently running")

    base = ["playerctl", "-p", p]
    _, status, _ = _run(base + ["status"])
    _, title, _ = _run(base + ["metadata", "title"])
    _, artist, _ = _run(base + ["metadata", "artist"])
    _, album, _ = _run(base + ["metadata", "album"])

    return {
        "ok": True,
        "player": p,
        "status": status.lower() or "unknown",
        "title": title or "",
        "artist": artist or "",
        "album": album or "",
        "content": f"{artist} — {title}" if title else f"Player: {p} ({status})",
        "response": f"{artist} — {title}" if title else f"Player: {p} ({status})",
    }


# ──────────────────────────────────────────────────────────────
# Playback control
# ──────────────────────────────────────────────────────────────

def _playerctl(cmd: str, player: Optional[str] = None, extra: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run a playerctl command. Returns normalized result dict."""
    if not _has("playerctl"):
        if not platform.LINUX:
            return _err("MPRIS/playerctl media control is Linux-only on this backend")
        return _err(
            "playerctl not installed — run: sudo apt install playerctl",
            install_hint="sudo apt install playerctl",
        )

    if player:
        p = resolve_player_target(player, command=cmd)
    else:
        p = get_active_player(command=cmd)
    if not p:
        suffix = f" matching '{player}'" if player else ""
        return _err(f"No media player{suffix} is currently running")

    argv = ["playerctl", "-p", p, cmd] + (extra or [])
    ok, stdout, stderr = _run(argv)

    if ok:
        info = get_player_info(p)
        now_playing = ""
        if info.get("title"):
            artist = str(info.get("artist") or "").strip()
            title = str(info.get("title") or "").strip()
            now_playing = f" ({artist} — {title})" if artist else f" ({title})"
        friendly = {
            "play": f"▶ Playing — {p}{now_playing}",
            "pause": f"⏸ Paused — {p}{now_playing}",
            "stop": f"⏹ Stopped — {p}{now_playing}",
            "next": f"⏭ Next track — {p}{now_playing}",
            "previous": f"⏮ Previous track — {p}{now_playing}",
            "play-pause": f"⏯ Toggled — {p}{now_playing}",
        }.get(cmd, f"{cmd} — {p}")
        return {"ok": True, "player": p, "cmd": cmd, "media": info, "content": friendly, "response": friendly}
    else:
        msg = f"Failed to {cmd} {p}: {stderr or 'unknown error'}"
        return {"ok": False, "player": p, "cmd": cmd, "error": stderr, "content": msg, "response": msg}


def play(player: Optional[str] = None) -> Dict[str, Any]:
    """Resume / start playback."""
    return _playerctl("play", player)


def pause(player: Optional[str] = None) -> Dict[str, Any]:
    """Pause playback."""
    return _playerctl("pause", player)


def play_pause(player: Optional[str] = None) -> Dict[str, Any]:
    """Toggle play/pause."""
    return _playerctl("play-pause", player)


def stop(player: Optional[str] = None) -> Dict[str, Any]:
    """
    Stop playback.
    Spotify does NOT support MPRIS2 'stop' — transparently uses 'pause' instead.
    VLC, MPV and others get a true stop.
    """
    p = player or get_active_player()
    if not p:
        return _err("No media player is currently running")

    if _is_pause_only(p):
        result = _playerctl("pause", p)
        if result.get("ok"):
            result["content"] = f"⏸ Paused (Spotify doesn't support Stop — paused instead)"
            result["response"] = result["content"]
            result["note"] = "Spotify does not implement MPRIS2 Stop; used Pause"
        return result

    return _playerctl("stop", p)


def next_track(player: Optional[str] = None) -> Dict[str, Any]:
    """Skip to next track."""
    return _playerctl("next", player)


def previous_track(player: Optional[str] = None) -> Dict[str, Any]:
    """Go to previous track."""
    return _playerctl("previous", player)


def seek(seconds: float, player: Optional[str] = None) -> Dict[str, Any]:
    """
    Seek forward (positive) or backward (negative) by seconds.
    Uses playerctl position offset (microseconds).
    """
    p = player or get_active_player()
    if not p:
        return _err("No media player is currently running")

    # playerctl seek takes seconds directly (not microseconds in newer versions)
    sign = "+" if seconds >= 0 else ""
    ok, _, err = _run(["playerctl", "-p", p, "position", f"{sign}{seconds}"])
    if ok:
        return _ok(f"Seeked {seconds:+.0f}s in {p}")
    return _err(f"Seek failed: {err}", player=p)


# ──────────────────────────────────────────────────────────────
# Volume control
# ──────────────────────────────────────────────────────────────

def get_volume() -> Dict[str, Any]:
    """Return current system volume as integer 0–100."""
    portable = platform.get_volume()
    if portable is not None:
        return {"ok": True, "volume": portable, "method": "platform",
                "content": f"Volume: {portable}%", "response": f"Volume: {portable}%"}

    if _has("pactl"):
        ok, out, _ = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
        if ok:
            m = re.search(r"(\d+)%", out)
            if m:
                vol = int(m.group(1))
                return {"ok": True, "volume": vol, "method": "pactl",
                        "content": f"Volume: {vol}%", "response": f"Volume: {vol}%"}

    if _has("amixer"):
        ok, out, _ = _run(["amixer", "get", "Master"])
        if ok:
            m = re.search(r"\[(\d+)%\]", out)
            if m:
                vol = int(m.group(1))
                return {"ok": True, "volume": vol, "method": "amixer",
                        "content": f"Volume: {vol}%", "response": f"Volume: {vol}%"}

    msg = "No volume control available"
    if platform.WINDOWS:
        msg += ". Install pycaw/comtypes for Windows endpoint volume support."
    elif platform.LINUX:
        msg += ". Install pactl: sudo apt install pulseaudio-utils."
    return _err(msg)


def set_volume(level: int, player: Optional[str] = None) -> Dict[str, Any]:
    """
    Set system volume to level (0–100).
    Uses pactl → amixer → playerctl fallback chain.
    """
    level = max(0, min(100, int(level)))

    if platform.set_volume(level):
        return {"ok": True, "volume": level, "method": "platform",
                "content": f"🔊 Volume set to {level}%", "response": f"Volume set to {level}%"}

    if _has("pactl"):
        ok, _, err = _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
        if ok:
            return {"ok": True, "volume": level, "method": "pactl",
                    "content": f"🔊 Volume set to {level}%", "response": f"Volume set to {level}%"}

    if _has("amixer"):
        ok, _, err = _run(["amixer", "set", "Master", f"{level}%"])
        if ok:
            return {"ok": True, "volume": level, "method": "amixer",
                    "content": f"🔊 Volume set to {level}%", "response": f"Volume set to {level}%"}

    # playerctl volume: 0.0–1.0
    if _has("playerctl"):
        p = player or get_active_player()
        if p:
            vol_float = round(level / 100.0, 2)
            ok, _, err = _run(["playerctl", "-p", p, "volume", str(vol_float)])
            if ok:
                return {"ok": True, "volume": level, "method": "playerctl", "player": p,
                        "content": f"🔊 Volume set to {level}%", "response": f"Volume set to {level}%"}

    msg = "Volume control unavailable"
    hint = None
    if platform.WINDOWS:
        msg += ". Install pycaw/comtypes for Windows endpoint volume support."
        hint = "pip install pycaw comtypes"
    elif platform.LINUX:
        msg += ". Install pactl: sudo apt install pulseaudio-utils."
        hint = "sudo apt install pulseaudio-utils"
    return _err(msg, install_hint=hint)


def mute(muted: bool = True) -> Dict[str, Any]:
    """Mute or unmute system audio."""
    state = "muted" if muted else "unmuted"
    icon = "🔇" if muted else "🔊"

    if platform.set_muted(muted):
        return _ok(f"{icon} Audio {state}")

    if _has("pactl"):
        val = "1" if muted else "0"
        ok, _, _ = _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", val])
        if ok:
            return _ok(f"{icon} Audio {state}")

    if _has("amixer"):
        val = "mute" if muted else "unmute"
        ok, _, _ = _run(["amixer", "set", "Master", val])
        if ok:
            return _ok(f"{icon} Audio {state}")

    msg = "Mute control unavailable"
    if platform.WINDOWS:
        msg += ". Install pycaw/comtypes for Windows endpoint mute support."
    elif platform.LINUX:
        msg += ". Install pactl: sudo apt install pulseaudio-utils."
    return _err(msg)


def unmute() -> Dict[str, Any]:
    """Unmute system audio."""
    return mute(muted=False)


def toggle_mute() -> Dict[str, Any]:
    """Toggle mute state."""
    if _has("pactl"):
        ok, _, _ = _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
        if ok:
            return _ok("🔀 Mute toggled")

    # Fallback: read state then flip
    vol = get_volume()
    if vol.get("ok"):
        # Rough heuristic: if volume is readable, toggle via mute state
        ok2, out, _ = _run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
        if ok2:
            currently_muted = "yes" in out.lower()
            return mute(not currently_muted)

    return _err("Toggle mute unavailable")


# ──────────────────────────────────────────────────────────────
# Clipboard (X11/Wayland auto-detect)
# ──────────────────────────────────────────────────────────────

def _clipboard_backend() -> str:
    """Detect best available clipboard backend."""
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "")

    if wayland_display or session == "wayland":
        if _has("wl-copy"):
            return "wayland"

    if _has("xclip"):
        return "xclip"
    if _has("xsel"):
        return "xsel"
    return "qt"  # Qt fallback (works inside the GUI process)


def clipboard_set(text: str) -> Dict[str, Any]:
    """Write text to clipboard, auto-detecting X11 vs Wayland."""
    if platform.copy_to_clipboard(text):
        return _ok("📋 Clipboard set")

    backend = _clipboard_backend()

    if backend == "wayland":
        try:
            p = subprocess.run(
                ["wl-copy"], input=text.encode("utf-8"),
                capture_output=True, timeout=5, check=False,
            )
            if p.returncode == 0:
                return _ok("📋 Clipboard set")
        except Exception:
            pass

    if backend in ("xclip", "qt"):  # try xclip even as fallback
        if _has("xclip"):
            try:
                p = subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode("utf-8"),
                    capture_output=True, timeout=5, check=False,
                )
                if p.returncode == 0:
                    return _ok("📋 Clipboard set (xclip)")
            except Exception:
                pass

    if _has("xsel"):
        try:
            p = subprocess.run(
                ["xsel", "--clipboard", "--input"],
                input=text.encode("utf-8"),
                capture_output=True, timeout=5, check=False,
            )
            if p.returncode == 0:
                return _ok("📋 Clipboard set (xsel)")
        except Exception:
            pass

    # Qt fallback (must be called from GUI thread)
    try:
        from eli.gui.qt_compat import QApplication
        app = QApplication.instance()
        if app:
            app.clipboard().setText(text)
            return _ok("📋 Clipboard set (Qt)")
    except Exception:
        pass

    return _err(
        "No clipboard backend available. "
        "Install xclip (sudo apt install xclip) or wl-clipboard (sudo apt install wl-clipboard)."
    )


def clipboard_get() -> Dict[str, Any]:
    """Read text from clipboard."""
    text = platform.get_clipboard()
    if text:
        return {"ok": True, "text": text, "content": text, "response": text}

    backend = _clipboard_backend()

    if backend == "wayland":
        ok, out, _ = _run(["wl-paste", "--no-newline"])
        if ok:
            return {"ok": True, "text": out, "content": out, "response": out}

    if _has("xclip"):
        ok, out, _ = _run(["xclip", "-selection", "clipboard", "-o"])
        if ok:
            return {"ok": True, "text": out, "content": out, "response": out}

    if _has("xsel"):
        ok, out, _ = _run(["xsel", "--clipboard", "--output"])
        if ok:
            return {"ok": True, "text": out, "content": out, "response": out}

    try:
        from eli.gui.qt_compat import QApplication
        app = QApplication.instance()
        if app:
            text = app.clipboard().text()
            return {"ok": True, "text": text, "content": text, "response": text}
    except Exception:
        pass

    return {"ok": False, "text": "", "content": "", "response": "", "error": "No clipboard backend"}
