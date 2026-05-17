"""
Media runtime control for ELI.

Owns:
- YouTube/mpv local playback
- targeted youtube/mpv play/pause/stop/next/previous
- Spotify query playback
- NOOP response handling

This module deliberately does not own STT, wake words, routing, or GUI logic.
"""


import json
import os
import shutil
import subprocess
import time
import urllib.parse
from typing import Any, Callable, Mapping


PLAY_ACTIONS = {"PLAY_MEDIA", "MEDIA_PLAY", "PLAY"}
PAUSE_ACTIONS = {"PAUSE_MEDIA", "MEDIA_PAUSE", "PAUSE"}
STOP_ACTIONS = {"STOP_MEDIA", "MEDIA_STOP", "STOP"}
NEXT_ACTIONS = {"NEXT_MEDIA", "MEDIA_NEXT", "NEXT"}
PREVIOUS_ACTIONS = {"PREVIOUS_MEDIA", "MEDIA_PREVIOUS", "PREVIOUS", "PREV"}

YOUTUBE_TARGETS = {"youtube", "yt", "mpv"}
SPOTIFY_TARGETS = {"spotify"}


def _str(x: Any) -> str:
    return str(x or "").strip()


def _lower(x: Any) -> str:
    return _str(x).lower()


def _run(argv: list[str], timeout: float = 3.0) -> tuple[bool, str, str]:
    try:
        r = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return False, "", str(e)


def _args_dict(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return dict(args)
    return {}


def _target(args: Mapping[str, Any]) -> str:
    raw = (
        args.get("target")
        or args.get("service")
        or args.get("provider")
        or args.get("player")
        or ""
    )
    t = _lower(raw)
    aliases = {
        "you tube": "youtube",
        "yt": "youtube",
        "youtube.com": "youtube",
        "mpv": "mpv",
        "spotify": "spotify",
    }
    return aliases.get(t, t)


def _query(args: Mapping[str, Any]) -> str:
    return _str(
        args.get("query")
        or args.get("text")
        or args.get("song")
        or args.get("title")
        or args.get("q")
        or ""
    )


def _clean_youtube_query(query: str) -> str:
    q = _str(query).lower()
    for prefix in (
        "play youtube ",
        "youtube play ",
        "play yt ",
        "yt play ",
        "play mpv ",
        "mpv play ",
        "youtube ",
        "yt ",
        "mpv ",
        "play ",
    ):
        if q.startswith(prefix):
            q = q[len(prefix):].strip()
            break
    q = q.replace(" on youtube", "").replace(" on yt", "").replace(" on mpv", "")
    return q.strip()


def _mpv_socket() -> str:
    return os.environ.get("ELI_YOUTUBE_MPV_IPC", "/tmp/eli_youtube_mpv.sock")


def _mpv_ipc(command: str) -> bool:
    sock = _mpv_socket()
    if not sock or not os.path.exists(sock) or not shutil.which("socat"):
        return False

    cmd = _lower(command)
    payloads = {
        "pause": {"command": ["set_property", "pause", True]},
        "play": {"command": ["set_property", "pause", False]},
        "resume": {"command": ["set_property", "pause", False]},
        "stop": {"command": ["stop"]},
        "close": {"command": ["quit"]},
        "next": {"command": ["playlist-next", "weak"]},
        "previous": {"command": ["playlist-prev", "weak"]},
        "prev": {"command": ["playlist-prev", "weak"]},
    }

    payload = payloads.get(cmd)
    if not payload:
        return False

    try:
        r = subprocess.run(
            ["socat", "-", sock],
            input=json.dumps(payload) + "\n",
            capture_output=True,
            text=True,
            timeout=2,
        )
        return r.returncode == 0
    except Exception:
        return False


def _mpv_control(command: str) -> str:
    cmd = _lower(command)
    ipc_cmd = "play" if cmd == "resume" else cmd

    if _mpv_ipc(ipc_cmd):
        labels = {
            "pause": "⏸ Paused — youtube/mpv",
            "play": "▶ Playing — youtube/mpv",
            "resume": "▶ Playing — youtube/mpv",
            "stop": "⏹ Stopped — youtube/mpv",
            "close": "Closed youtube/mpv",
            "next": "⏭ Next — youtube/mpv",
            "previous": "⏮ Previous — youtube/mpv",
            "prev": "⏮ Previous — youtube/mpv",
        }
        return labels.get(cmd, f"{cmd} — youtube/mpv")

    if shutil.which("playerctl"):
        player_cmd = {
            "pause": "pause",
            "play": "play",
            "resume": "play",
            "stop": "stop",
            "next": "next",
            "previous": "previous",
            "prev": "previous",
        }.get(cmd)

        if player_cmd:
            ok, _, err = _run(["playerctl", "-p", "mpv", player_cmd], timeout=2)
            if ok:
                labels = {
                    "pause": "⏸ Paused — mpv",
                    "play": "▶ Playing — mpv",
                    "resume": "▶ Playing — mpv",
                    "stop": "⏹ Stopped — mpv",
                    "next": "⏭ Next — mpv",
                    "previous": "⏮ Previous — mpv",
                    "prev": "⏮ Previous — mpv",
                }
                return labels.get(cmd, f"{cmd} — mpv")
            return f"Could not control mpv: {err or 'playerctl failed'}"

    return "Could not control youtube/mpv. Need mpv IPC socket or playerctl."


def youtube_play(query: str) -> str:
    q = _clean_youtube_query(query)
    if not q:
        return "Say what to play."

    if not shutil.which("mpv"):
        return "mpv is not installed; cannot play YouTube locally."

    sock = _mpv_socket()

    # Stop previous ELI-controlled mpv instance if possible.
    try:
        _mpv_ipc("close")
        time.sleep(0.15)
    except Exception:
        pass

    volume = os.environ.get("ELI_YOUTUBE_MPV_VOLUME", "35").strip() or "35"

    argv = [
        "mpv",
        "--no-terminal",
        "--force-window=yes",
        f"--input-ipc-server={sock}",
        f"--volume={volume}",
        "ytdl://ytsearch1:" + q,
    ]

    try:
        subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"YouTube: playing first result via mpv: {q}"
    except Exception as e:
        return f"Could not start YouTube/mpv playback: {e}"


def open_spotify() -> str:
    candidates = [
        ["spotify"],
        ["flatpak", "run", "com.spotify.Client"],
        ["snap", "run", "spotify"],
        ["gtk-launch", "spotify"],
        ["gtk-launch", "com.spotify.Client"],
        ["xdg-open", "spotify:"],
    ]

    for argv in candidates:
        if not shutil.which(argv[0]):
            continue
        try:
            subprocess.Popen(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return "Opened app: spotify"
        except Exception:
            continue

    return "Could not open spotify. Tried: spotify, flatpak com.spotify.Client, snap spotify, gtk-launch, xdg-open spotify:"


def spotify_query(query: str) -> str:
    q = _str(query)
    if not q:
        return "Say what to play."

    encoded = urllib.parse.quote(q)
    uri = f"spotify:search:{encoded}"

    # Ensure Spotify has at least been asked to launch.
    try:
        open_spotify()
        time.sleep(0.35)
    except Exception:
        pass

    if shutil.which("dbus-send"):
        try:
            subprocess.run(
                [
                    "dbus-send",
                    "--print-reply",
                    "--dest=org.mpris.MediaPlayer2.spotify",
                    "/org/mpris/MediaPlayer2",
                    "org.mpris.MediaPlayer2.Player.OpenUri",
                    f"string:{uri}",
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except Exception:
            pass

    if shutil.which("playerctl"):
        try:
            subprocess.run(
                ["playerctl", "-p", "spotify", "play"],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except Exception:
            pass

    return f"Searching Spotify for: {q}"


def install_media_executor(original_execute_action: Callable[..., Any]) -> Callable[..., Any]:
    """
    Return execute_action wrapper preserving current ELI media behaviour.
    """

    def execute_action(action: Any, args: Any = None, *a: Any, **kw: Any) -> Any:
        act = _str(action).upper()
        data = _args_dict(args)
        target = _target(data)
        query = _query(data)

        if act == "NOOP":
            return data.get("response") or data.get("message") or ""

        if act == "OPEN_APP" and _lower(data.get("name")) == "spotify":
            return open_spotify()

        if target in YOUTUBE_TARGETS:
            if act in PLAY_ACTIONS:
                if query:
                    return youtube_play(query)
                return _mpv_control("play")

            if act in PAUSE_ACTIONS:
                return _mpv_control("pause")

            if act in STOP_ACTIONS:
                return _mpv_control("stop")

            if act in NEXT_ACTIONS:
                return _mpv_control("next")

            if act in PREVIOUS_ACTIONS:
                return _mpv_control("previous")

        if target in SPOTIFY_TARGETS and act in PLAY_ACTIONS and query:
            return spotify_query(query)

        return original_execute_action(action, args, *a, **kw)

    execute_action._eli_media_runtime_installed = True  # type: ignore[attr-defined]
    return execute_action
