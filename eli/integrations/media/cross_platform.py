"""Cross-platform Spotify control and mpv IPC.

Linux uses MPRIS/dbus + playerctl. macOS uses AppleScript + URI schemes.
Windows uses URI schemes + virtual media keys. Android/Termux uses intents
and termux-open-url. All paths degrade gracefully — never raise.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.parse
from typing import Any

from eli.utils.log import get_logger

log = get_logger(__name__)

try:
    from eli.utils import platform_compat as pc
except Exception:  # pragma: no cover
    import sys as _sys

    pc = type("_PC", (), {
        "LINUX": _sys.platform.startswith("linux"),
        "MACOS": _sys.platform == "darwin",
        "WINDOWS": _sys.platform.startswith("win"),
        "ANDROID": False,
    })()


def _run(argv: list[str], *, timeout: float = 5.0) -> tuple[bool, str, str]:
    try:
        r = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as exc:
        return False, "", str(exc)


def is_process_running(name: str) -> bool:
    """True when a process whose name contains `name` is running."""
    needle = (name or "").strip().lower()
    if not needle:
        return False

    if pc.LINUX or pc.MACOS:
        ok, out, _ = _run(["pgrep", "-if", needle], timeout=4)
        if ok and out:
            return True
        ok, out, _ = _run(["ps", "-A", "-o", "comm="], timeout=4)
        if ok:
            return any(needle in ln.strip().lower() for ln in out.splitlines())
        return False

    if pc.WINDOWS:
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if ps:
            script = (
                f"if (Get-Process -ErrorAction SilentlyContinue | "
                f"Where-Object {{ $_.ProcessName -like '*{needle}*' }}) "
                f"{{ exit 0 }} else {{ exit 1 }}"
            )
            ok, _, _ = _run([ps, "-NoProfile", "-Command", script], timeout=5)
            return ok
        ok, out, _ = _run(["tasklist"], timeout=5)
        return ok and needle in out.lower()

    if pc.ANDROID:
        ok, out, _ = _run(["pidof", needle], timeout=3)
        if ok and out.strip():
            return True
        ok, out, _ = _run(["ps"], timeout=3)
        return ok and needle in out.lower()

    return False


def _macos_osascript(script: str) -> tuple[bool, str]:
    osascript = shutil.which("osascript")
    if not osascript:
        return False, "osascript not available"
    ok, out, err = _run([osascript, "-e", script], timeout=8)
    return ok, out or err


def _windows_powershell(script: str) -> tuple[bool, str]:
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return False, "PowerShell not available"
    ok, out, err = _run([ps, "-NoProfile", "-Command", script], timeout=8)
    return ok, out or err


def _open_uri_fallback(uri: str) -> bool:
    u = str(uri or "").strip()
    if not u:
        return False
    try:
        from eli.utils.platform_compat import open_app_uri, open_url
        if u.startswith("spotify:") or "open.spotify.com" in u.lower():
            if spotify_launch_if_needed():
                time.sleep(0.6)
            return bool(open_app_uri(u))
        if open_app_uri(u):
            return True
        return bool(open_url(u))
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return False


def _android_open_uri(uri: str) -> bool:
    if shutil.which("termux-open-url"):
        ok, _, _ = _run(["termux-open-url", uri], timeout=5)
        if ok:
            return True
    if shutil.which("am"):
        ok, _, _ = _run(
            ["am", "start", "-a", "android.intent.action.VIEW", "-d", uri],
            timeout=5,
        )
        return ok
    return _open_uri_fallback(uri)


def spotify_launch_if_needed() -> bool:
    """Ensure Spotify is running; launch via platform conventions if not."""
    if spotify_running():
        return True
    try:
        from eli.execution.media_runtime import open_spotify
        msg = open_spotify()
        return "Could not open" not in str(msg)
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    if pc.MACOS:
        ok, _ = _macos_osascript('tell application "Spotify" to launch')
        return ok
    if pc.WINDOWS:
        return _open_uri_fallback("spotify:")
    if pc.ANDROID:
        return _android_open_uri("spotify:")
    return False


def spotify_running() -> bool:
    if pc.ANDROID:
        return is_process_running("com.spotify.music") or is_process_running("spotify")
    return is_process_running("spotify") or is_process_running("Spotify")


def spotify_open_uri(uri: str) -> bool:
    """Open a spotify: or https://open.spotify.com/ URI in the Spotify app."""
    u = str(uri or "").strip()
    if not u:
        return False

    if pc.LINUX and shutil.which("dbus-send"):
        ok, _, _ = _run([
            "dbus-send", "--print-reply",
            "--dest=org.mpris.MediaPlayer2.spotify",
            "/org/mpris/MediaPlayer2",
            "org.mpris.MediaPlayer2.Player.OpenUri",
            f"string:{u}",
        ], timeout=5)
        if ok:
            return True

    if pc.MACOS:
        safe = u.replace('"', '\\"')
        ok, _ = _macos_osascript(
            f'tell application "Spotify"\n'
            f'  if not running then launch\n'
            f'  open location "{safe}"\n'
            f'end tell'
        )
        if ok:
            return True
        return _open_uri_fallback(u)

    if pc.WINDOWS:
        if _open_uri_fallback(u):
            return True
        ok, _ = _windows_powershell(f'Start-Process "{u.replace(chr(34), "")}"')
        return ok

    if pc.ANDROID:
        return _android_open_uri(u)

    return _open_uri_fallback(u)


def spotify_search(query: str, prefer: str | None = None) -> bool:
    raw = str(query or "").strip()
    if not raw:
        return False
    spotify_launch_if_needed()
    time.sleep(0.4)
    q = urllib.parse.quote(raw)
    tab = {
        "playlist": "playlists", "playlists": "playlists",
        "album": "albums", "albums": "albums",
        "artist": "artists", "artists": "artists",
        "track": "tracks", "tracks": "tracks",
    }.get(prefer or "")
    if tab:
        if spotify_open_uri(f"spotify:search:{raw}/{tab}"):
            return True
        if spotify_open_uri(f"https://open.spotify.com/search/{q}/{tab}"):
            return True
    if spotify_open_uri(f"spotify:search:{raw}"):
        return True
    return spotify_open_uri(f"spotify:search:{q}")


def _spotify_scrape_uri(name: str, kind: str) -> str | None:
    """Resolve a playlist/album/artist name to spotify:<kind>:<id> via search HTML."""
    import re as _re
    import urllib.request as _ureq

    q = str(name or "").strip()
    if not q:
        return None
    plural = {"playlist": "playlists", "album": "albums", "artist": "artists"}.get(kind, kind)
    url = f"https://open.spotify.com/search/{urllib.parse.quote(q)}/{plural}"
    patterns = {
        "playlist": (
            r'"uri"\s*:\s*"spotify:playlist:([A-Za-z0-9]+)"',
            r'spotify:playlist:([A-Za-z0-9]+)',
        ),
        "album": (
            r'"uri"\s*:\s*"spotify:album:([A-Za-z0-9]+)"',
            r'spotify:album:([A-Za-z0-9]+)',
        ),
        "artist": (
            r'"uri"\s*:\s*"spotify:artist:([A-Za-z0-9]+)"',
            r'spotify:artist:([A-Za-z0-9]+)',
        ),
    }.get(kind, ())
    try:
        req = _ureq.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        )
        with _ureq.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        for pat in patterns:
            m = _re.search(pat, html)
            if m:
                return f"spotify:{kind}:{m.group(1)}"
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return None


def spotify_resolve_playlist_uri(name: str) -> str | None:
    return _spotify_scrape_uri(name, "playlist")


def spotify_resolve_album_uri(name: str, artist: str | None = None) -> str | None:
    query = f"{name} {artist}".strip() if artist else name
    return _spotify_scrape_uri(query, "album")


def spotify_resolve_artist_uri(name: str) -> str | None:
    return _spotify_scrape_uri(name, "artist")


def spotify_open_liked_songs() -> bool:
    """Open the user's Liked Songs collection — try every URI form Spotify accepts."""
    uris = (
        "spotify:collection:tracks",
        "https://open.spotify.com/collection/tracks",
    )
    for uri in uris:
        if spotify_open_uri(uri):
            return True
    if pc.LINUX and shutil.which("playerctl"):
        ok, _, _ = _run(["playerctl", "-p", "spotify", "open", "spotify:collection:tracks"])
        if ok:
            return True
    return False


def spotify_shuffle(player: str | None = None, mode: str = "Toggle") -> dict[str, Any]:
    """Toggle or set shuffle via playerctl."""
    p = (player or "spotify").strip() or "spotify"
    if pc.LINUX and shutil.which("playerctl"):
        ok, out, err = _run(["playerctl", "-p", p, "shuffle", mode], timeout=5)
        if ok:
            state = out or mode
            msg = f"🔀 Shuffle {state.lower()} — {p}"
            return {"ok": True, "player": p, "content": msg, "response": msg}
        return {"ok": False, "player": p, "error": err or "shuffle failed",
                "content": f"Couldn't toggle shuffle on {p}.",
                "response": f"Couldn't toggle shuffle on {p}."}
    if pc.MACOS:
        ok, _ = _macos_osascript(
            'tell application "Spotify"\n'
            '  if not running then return "off"\n'
            '  set shuffling to not shuffling\n'
            '  return shuffling as string\n'
            'end tell'
        )
        if ok:
            msg = f"🔀 Shuffle toggled — Spotify"
            return {"ok": True, "player": "spotify", "content": msg, "response": msg}
    return {"ok": False, "error": "shuffle unavailable",
            "content": "Shuffle control isn't available on this system.",
            "response": "Shuffle control isn't available on this system."}


def spotify_set_loop(player: str | None = None, mode: str | None = None) -> dict[str, Any]:
    """Set or cycle repeat/loop mode (None, Track, Playlist)."""
    p = (player or "spotify").strip() or "spotify"
    current = spotify_loop_status()
    if mode is None:
        mode = {"None": "Track", "Track": "Playlist", "Playlist": "None"}.get(current, "Track")
    if pc.LINUX and shutil.which("playerctl"):
        ok, out, err = _run(["playerctl", "-p", p, "loop", mode], timeout=5)
        if ok:
            state = out or mode
            msg = f"🔁 Repeat {state.lower()} — {p}"
            return {"ok": True, "player": p, "content": msg, "response": msg}
        return {"ok": False, "player": p, "error": err or "loop failed",
                "content": f"Couldn't set repeat on {p}.",
                "response": f"Couldn't set repeat on {p}."}
    if pc.MACOS:
        script = {
            "None": 'set repeating to false',
            "Track": 'set repeating to true',
            "Playlist": 'set repeating to true',
        }.get(mode, 'set repeating to false')
        ok, _ = _macos_osascript(f'tell application "Spotify" to {script}')
        if ok:
            msg = f"🔁 Repeat {mode.lower()} — Spotify"
            return {"ok": True, "player": "spotify", "content": msg, "response": msg}
    return {"ok": False, "error": "repeat unavailable",
            "content": "Repeat control isn't available on this system.",
            "response": "Repeat control isn't available on this system."}


def spotify_play() -> bool:
    """Start/resume Spotify; return True only when playback is confirmed."""
    if pc.LINUX:
        if shutil.which("playerctl"):
            _run(["playerctl", "-p", "spotify", "play"], timeout=5)
        if shutil.which("dbus-send"):
            _run([
                "dbus-send", "--print-reply",
                "--dest=org.mpris.MediaPlayer2.spotify",
                "/org/mpris/MediaPlayer2",
                "org.mpris.MediaPlayer2.Player.Play",
            ], timeout=5)
        return spotify_wait_playing(timeout=6.0)

    if pc.MACOS:
        ok, _ = _macos_osascript('tell application "Spotify" to play')
        if ok:
            return spotify_wait_playing(timeout=6.0)
        try:
            from eli.integrations.mpris import playerctl_backend as pb
            r = pb._macos_media("play")
            return bool(r.get("ok")) and spotify_wait_playing(timeout=4.0)
        except Exception:
            log.debug("suppressed exception", exc_info=True)
        return False

    if pc.WINDOWS:
        try:
            from eli.integrations.mpris import playerctl_backend as pb
            r = pb._windows_media_vk("play")
            if r.get("ok"):
                return spotify_wait_playing(timeout=4.0)
        except Exception:
            log.debug("suppressed exception", exc_info=True)
        return False

    if pc.ANDROID:
        return _android_open_uri("spotify:")

    return False


def spotify_is_playing() -> bool:
    if pc.LINUX and shutil.which("playerctl"):
        ok, out, _ = _run(["playerctl", "-p", "spotify", "status"], timeout=5)
        if ok and "playing" in out.lower():
            return True

    if pc.MACOS:
        ok, out = _macos_osascript(
            'tell application "Spotify" to return (player state as string)'
        )
        if ok and "playing" in out.lower():
            return True

    if pc.WINDOWS and shutil.which("playerctl"):
        ok, out, _ = _run(["playerctl", "-p", "spotify", "status"], timeout=5)
        if ok and "playing" in out.lower():
            return True

    return False


def spotify_wait_playing(timeout: float = 8.0, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if spotify_is_playing():
            return True
        time.sleep(max(0.05, interval))
    return False


def spotify_wait_running(timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if spotify_running():
            return True
        time.sleep(0.5)
    return False


def spotify_loop_status() -> str:
    if pc.LINUX and shutil.which("playerctl"):
        ok, out, _ = _run(["playerctl", "-p", "spotify", "loop"], timeout=5)
        if ok:
            return out
    if pc.MACOS:
        ok, out = _macos_osascript(
            'tell application "Spotify" to return repeating'
        )
        if ok:
            low = out.lower()
            if "one" in low or "track" in low:
                return "Track"
            if "all" in low or "playlist" in low:
                return "Playlist"
            if "false" in low or "off" in low:
                return "None"
    return ""


def spotify_clear_track_repeat() -> bool:
    if spotify_loop_status() != "Track":
        return False
    if pc.LINUX and shutil.which("playerctl"):
        _run(["playerctl", "-p", "spotify", "loop", "None"], timeout=5)
        return spotify_loop_status() != "Track"
    if pc.MACOS:
        ok, _ = _macos_osascript(
            'tell application "Spotify" to set repeating to false'
        )
        return ok
    return False


def spotify_live_meta(player: str = "spotify") -> tuple[str, str, str]:
    """Return (status_head, artist, title) from the live player when possible."""
    if pc.LINUX or (shutil.which("playerctl") and not pc.MACOS):
        try:
            from eli.integrations.mpris import playerctl_backend as _pcb
            st = _pcb.get_player_status(player)
            if st.get("ok"):
                artist = str(st.get("artist") or "").strip()
                title = str(st.get("title") or "").strip()
                status = str(st.get("status") or "").lower()
                if status == "playing":
                    head = "▶ Playing"
                elif status == "paused":
                    head = "⏸ Paused"
                elif status == "stopped":
                    head = "⏹ Stopped"
                else:
                    head = f"⏺ {status.capitalize()}" if status else "▶ Playing"
                return head, artist, title
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    if pc.MACOS:
        ok, out = _macos_osascript(
            'tell application "Spotify"\n'
            '  if not running then return ""\n'
            '  set t to name of current track\n'
            '  set a to artist of current track\n'
            '  set s to player state as string\n'
            '  return s & "|" & a & "|" & t\n'
            'end tell'
        )
        if ok and "|" in out:
            parts = out.split("|", 2)
            if len(parts) == 3:
                status, artist, title = (p.strip() for p in parts)
                head = "▶ Playing" if "playing" in status.lower() else (
                    "⏸ Paused" if "paused" in status.lower() else f"⏺ {status}"
                )
                return head, artist, title

    return "", "", ""


def mpv_socket_path() -> str:
    env = os.environ.get("ELI_YOUTUBE_MPV_IPC")
    if env:
        return env
    if pc.WINDOWS:
        return r"\\.\pipe\eli_youtube_mpv"
    import tempfile
    return os.path.join(tempfile.gettempdir(), "eli_youtube_mpv.sock")


def _is_windows_pipe(path: str) -> bool:
    p = str(path or "")
    return p.startswith("\\\\.\\pipe\\") or p.startswith(r"\\.\pipe")


def mpv_alive(sock_path: str | None = None) -> bool:
    p = sock_path or mpv_socket_path()
    if _is_windows_pipe(p):
        try:
            with open(p, "r+b", buffering=0):
                return True
        except Exception:
            return False
    if not os.path.exists(p):
        return False
    import socket as _sock
    try:
        with _sock.socket(_sock.AF_UNIX, _sock.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(p)
        return True
    except Exception:
        return False


def mpv_ipc_send(
    command: list[Any],
    *,
    sock_path: str | None = None,
    want_response: bool = False,
) -> Any:
    """Send one mpv JSON IPC command. Returns True/data or False/None."""
    p = sock_path or mpv_socket_path()
    payload = json.dumps({"command": command}) + "\n"

    if _is_windows_pipe(p):
        try:
            with open(p, "r+b", buffering=0) as pipe:
                pipe.write(payload.encode())
                if want_response:
                    buf = pipe.read(8192).decode("utf-8", "ignore")
                    for line in buf.splitlines():
                        try:
                            j = json.loads(line)
                            if isinstance(j, dict) and "data" in j:
                                return j["data"]
                        except Exception:
                            log.debug("suppressed exception", exc_info=True)
                    return None
                return True
        except Exception:
            return None if want_response else False

    if not os.path.exists(p):
        return None if want_response else False

    import socket as _sock
    try:
        with _sock.socket(_sock.AF_UNIX, _sock.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(p)
            s.sendall(payload.encode())
            if want_response:
                buf = s.recv(8192).decode("utf-8", "ignore")
                for line in buf.splitlines():
                    try:
                        j = json.loads(line)
                        if isinstance(j, dict) and "data" in j:
                            return j["data"]
                    except Exception:
                        log.debug("suppressed exception", exc_info=True)
                return None
        return True
    except Exception:
        return None if want_response else False
