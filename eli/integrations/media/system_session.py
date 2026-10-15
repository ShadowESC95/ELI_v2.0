"""What is playing, and control of it, on Windows and macOS (Linux uses MPRIS: eli.integrations.mpris).

Windows: the system media session (GlobalSystemMediaTransportControlsSessionManager), which every
player shown in the volume flyout reports to: Spotify, browsers, Media Player. Read and driven through
Windows PowerShell's WinRT bridge, so nothing extra is installed. PowerShell 7 has no WinRT bridge, so
powershell.exe is used.

macOS: Spotify and Music by AppleScript, only when one of them is running (telling an app that is not
running anything starts it). Other players get the system media keys (macos_media_key).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Dict, Optional

from eli.utils import platform_compat as pc
from eli.utils.log import get_logger

log = get_logger(__name__)

# ── Windows ─────────────────────────────────────────────────────────────────

_WIN_PRELUDE = r"""$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Await($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $null = $t.Wait(-1); $t.Result }
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
$null = [Windows.Media.MediaPlaybackAutoRepeatMode, Windows.Media, ContentType = WindowsRuntime]
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$s = $mgr.GetCurrentSession()
if ($null -eq $s) { '{}'; exit 0 }
"""

_WIN_BODY = {
    "info": r"""$p = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
$i = $s.GetPlaybackInfo()
[pscustomobject]@{ player = $s.SourceAppUserModelId; status = [string]$i.PlaybackStatus; artist = $p.Artist;
  title = $p.Title; shuffle = $i.IsShuffleActive; repeat = [string]$i.AutoRepeatMode } | ConvertTo-Json -Compress""",
    "play": "@{ ok = (Await ($s.TryPlayAsync()) ([bool])) } | ConvertTo-Json -Compress",
    "pause": "@{ ok = (Await ($s.TryPauseAsync()) ([bool])) } | ConvertTo-Json -Compress",
    "play-pause": "@{ ok = (Await ($s.TryTogglePlayPauseAsync()) ([bool])) } | ConvertTo-Json -Compress",
    "stop": "@{ ok = (Await ($s.TryStopAsync()) ([bool])) } | ConvertTo-Json -Compress",
    "next": "@{ ok = (Await ($s.TrySkipNextAsync()) ([bool])) } | ConvertTo-Json -Compress",
    "previous": "@{ ok = (Await ($s.TrySkipPreviousAsync()) ([bool])) } | ConvertTo-Json -Compress",
    "shuffle": r"""$on = -not [bool]$s.GetPlaybackInfo().IsShuffleActive
@{ ok = (Await ($s.TryChangeShuffleActiveAsync($on)) ([bool])); shuffle = $on } | ConvertTo-Json -Compress""",
    "repeat": r"""$next = switch ([string]$s.GetPlaybackInfo().AutoRepeatMode) { 'None' { 'Track' } 'Track' { 'List' } default { 'None' } }
@{ ok = (Await ($s.TryChangeAutoRepeatModeAsync([Windows.Media.MediaPlaybackAutoRepeatMode]::$next)) ([bool])); repeat = $next } | ConvertTo-Json -Compress""",
}


def windows_script(what: str) -> str:
    """The PowerShell for `what` (info, a playback command, shuffle, repeat). Public for the CI check
    that parses it on Windows."""
    return _WIN_PRELUDE + _WIN_BODY[what]


def _windows(what: str) -> Optional[Dict[str, Any]]:
    ps = shutil.which("powershell")
    if not ps:
        return None
    try:
        cp = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", windows_script(what)],
                            capture_output=True, text=True, timeout=20)
        out = (cp.stdout or "").strip().splitlines()
        return json.loads(out[-1]) if cp.returncode == 0 and out else None
    except Exception:
        log.debug("Windows media session unavailable", exc_info=True)
        return None


# ── macOS ───────────────────────────────────────────────────────────────────

MACOS_PLAYERS = ("Spotify", "Music")


def _osascript(script: str) -> Optional[str]:
    osa = shutil.which("osascript")
    if not osa:
        return None
    try:
        cp = subprocess.run([osa, "-e", script], capture_output=True, text=True, timeout=10)
        return cp.stdout.strip() if cp.returncode == 0 else None
    except Exception:
        log.debug("osascript failed", exc_info=True)
        return None


def macos_running_player() -> str:
    """Spotify or Music when running (the playing one, if both are), else "". Asked of System Events
    first: a script naming an app that is not installed does not even compile."""
    out = _osascript('tell application "System Events" to get name of every process whose '
                     'name is "Spotify" or name is "Music"')
    running = [n.strip() for n in (out or "").split(",") if n.strip() in MACOS_PLAYERS]
    if len(running) > 1:
        for app in running:
            if _osascript(f'tell application "{app}" to return player state as string') == "playing":
                return app
    return running[0] if running else ""


_MACOS_COMMAND = {"play": "play", "pause": "pause", "play-pause": "playpause", "next": "next track",
                  "previous": "previous track", "stop": "pause"}

# NX_KEYTYPE_* of the media keys, posted as the keyboard's own system-defined events. (System Events
# "key code 16/17/18" are the Y, U and T keys: until 2.5.17 that typed letters into the front app.)
_NX_KEY = {"play": 16, "pause": 16, "play-pause": 16, "stop": 16, "next": 17, "previous": 18,
           "volume_up": 0, "volume_down": 1, "mute": 7}


def macos_media_key_script(key: str) -> str:
    """JavaScript for Automation that presses one media key. Public for the CI compile check."""
    code = _NX_KEY[key]
    return ("ObjC.import('Cocoa'); ObjC.import('CoreGraphics');\n"
            "[true, false].forEach(function (down) {\n"
            f"  var data1 = ({code} << 16) | ((down ? 0xa : 0xb) << 8);\n"
            "  var e = $.NSEvent.otherEventWithTypeLocationModifierFlagsTimestampWindowNumberContextSubtypeData1Data2(\n"
            "    14, $.NSMakePoint(0, 0), down ? 0xa00 : 0xb00, 0, 0, $(), 8, data1, -1);\n"
            "  $.CGEventPost(0, e.CGEvent);\n"
            "});")


def macos_media_key(key: str) -> bool:
    osa = shutil.which("osascript")
    if not osa or key not in _NX_KEY:
        return False
    try:
        return subprocess.run([osa, "-l", "JavaScript", "-e", macos_media_key_script(key)],
                              capture_output=True, timeout=10).returncode == 0
    except Exception:
        log.debug("media key failed", exc_info=True)
        return False


# ── both ────────────────────────────────────────────────────────────────────

def info() -> Optional[Dict[str, Any]]:
    """{"player", "status" (playing/paused/stopped), "artist", "title"} of what the OS says is playing,
    or None."""
    if pc.WINDOWS:
        d = _windows("info")
        if not d or not d.get("title"):
            return None
        status = str(d.get("status") or "").lower()
        player = str(d.get("player") or "").split("!")[0].removesuffix(".exe")
        return {"player": player, "status": status if status in ("playing", "paused", "stopped") else status,
                "artist": str(d.get("artist") or ""), "title": str(d.get("title") or "")}
    if pc.MACOS:
        app = macos_running_player()
        if not app:
            return None
        out = _osascript(f'tell application "{app}"\n'
                         ' if player state is stopped then return "stopped||"\n'
                         ' return (player state as string) & "|" & (artist of current track) & "|" & (name of current track)\n'
                         'end tell')
        if not out or "|" not in out:
            return None
        status, artist, title = (out.split("|", 2) + ["", ""])[:3]
        return {"player": app, "status": status.strip().lower(), "artist": artist.strip(), "title": title.strip()}
    return None


def command(cmd: str) -> Optional[str]:
    """Send play/pause/play-pause/stop/next/previous to the player the OS knows about. Returns the
    player's name, or None when there was none to tell."""
    if pc.WINDOWS:
        d = _windows(cmd) if cmd in _WIN_BODY else None
        if d and d.get("ok"):
            return "the playing app"
        return None
    if pc.MACOS:
        app = macos_running_player()
        if app and cmd in _MACOS_COMMAND:
            if _osascript(f'tell application "{app}" to {_MACOS_COMMAND[cmd]}') is not None:
                return app
    return None


def toggle_shuffle() -> Optional[Dict[str, Any]]:
    """{"player", "shuffle": bool} after toggling shuffle, or None."""
    if pc.WINDOWS:
        d = _windows("shuffle")
        return {"player": "the playing app", "shuffle": bool(d.get("shuffle"))} if d and d.get("ok") else None
    if pc.MACOS:
        app = macos_running_player()
        if app:
            prop = "shuffling" if app == "Spotify" else "shuffle enabled"
            out = _osascript(f'tell application "{app}"\n set {prop} to not {prop}\n return {prop}\nend tell')
            if out in ("true", "false"):
                return {"player": app, "shuffle": out == "true"}
    return None


def cycle_repeat() -> Optional[Dict[str, Any]]:
    """{"player", "repeat": "none"|"track"|"list"} after moving repeat on (none → track → list), or None."""
    if pc.WINDOWS:
        d = _windows("repeat")
        return {"player": "the playing app", "repeat": str(d.get("repeat") or "").lower()} if d and d.get("ok") else None
    if pc.MACOS:
        app = macos_running_player()
        if app == "Music":
            out = _osascript('tell application "Music"\n'
                             ' if song repeat is off then\n  set song repeat to one\n'
                             ' else if song repeat is one then\n  set song repeat to all\n'
                             ' else\n  set song repeat to off\n end if\n'
                             ' return song repeat as string\nend tell')
            if out:
                return {"player": app, "repeat": {"one": "track", "all": "list"}.get(out, "none")}
        elif app == "Spotify":
            out = _osascript('tell application "Spotify"\n set repeating to not repeating\n return repeating\nend tell')
            if out in ("true", "false"):
                return {"player": app, "repeat": "list" if out == "true" else "none"}
    return None
