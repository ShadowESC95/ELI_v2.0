"""Shared YouTube playback helpers — mpv, yt-dlp clients, browser URLs.

Single source of truth for v2 (executor_enhanced) and v3 (effectors/media).
Works on Linux, macOS, and Windows wherever mpv + yt-dlp are installed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any

from eli.utils.log import get_logger

log = get_logger(__name__)


def yt_autoplay_enabled() -> bool:
    env = (os.environ.get("ELI_YT_AUTOPLAY") or "").strip().lower()
    if env in {"0", "false", "off", "no"}:
        return False
    if env in {"1", "true", "on", "yes"}:
        return True
    try:
        from eli.core.config import get as _cfg_get
        return bool(_cfg_get("youtube_autoplay", True))
    except Exception:
        return True


def yt_player_clients() -> list[str]:
    """yt-dlp YouTube clients to try, in order."""
    raw = (os.environ.get("ELI_YT_PLAYER_CLIENTS") or "").strip()
    if raw:
        return [("" if c.strip().lower() == "default" else c.strip())
                for c in raw.split(",") if c.strip()]
    return ["android", "tv", "ios", "mweb", ""]


def yt_is_client_bound_failure(stderr_tail: str) -> bool:
    low = str(stderr_tail or "").lower()
    if "empty playlist" in low or "unavailable" in low or "private video" in low:
        return False
    return "403" in low or "forbidden" in low


def mpv_numeric(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def mpv_load_confirmed(sock_path: str) -> bool:
    from eli.integrations.media.cross_platform import mpv_ipc_send
    idle = mpv_ipc_send(["get_property", "idle-active"], sock_path=sock_path, want_response=True)
    if idle is True:
        return False
    dur = mpv_ipc_send(["get_property", "duration"], sock_path=sock_path, want_response=True)
    if mpv_numeric(dur):
        return True
    pos = mpv_ipc_send(["get_property", "time-pos"], sock_path=sock_path, want_response=True)
    return mpv_numeric(pos)


def yt_resolve_watch_url(query: str) -> str | None:
    try:
        import urllib.parse as _up
        import urllib.request as _ureq
        url = f"https://www.youtube.com/results?search_query={_up.quote_plus(query)}"
        req = _ureq.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ELI/1.0)"},
        )
        with _ureq.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', html)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return None


def yt_resolve_watch_url_ytdlp(query: str) -> str | None:
    if not shutil.which("yt-dlp"):
        return None
    try:
        r = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--print", "url", f"ytsearch1:{query}"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            for line in (r.stdout or "").splitlines():
                url = line.strip()
                if url.startswith("http") and "watch?v=" in url:
                    return url
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    return None


def yt_mix_url(watch_url: str | None) -> str | None:
    if not watch_url:
        return watch_url
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", watch_url)
    if m:
        vid = m.group(1)
        return f"https://www.youtube.com/watch?v={vid}&list=RD{vid}"
    return watch_url


def yt_apply_browser_autoplay(url: str) -> str:
    if not url or "youtube.com" not in url:
        return url
    sep = "&" if "?" in url else "?"
    extras: list[str] = []
    if "autoplay=" not in url.lower():
        extras.append("autoplay=1")
    if "list=RD" in url and "start_radio=" not in url.lower():
        extras.append("start_radio=1")
    return f"{url}{sep}{'&'.join(extras)}" if extras else url


def yt_browser_play_url(query: str) -> str:
    import urllib.parse as _up
    watch = yt_resolve_watch_url(query) or yt_resolve_watch_url_ytdlp(query)
    if watch and yt_autoplay_enabled():
        watch = yt_mix_url(watch)
    if watch:
        return yt_apply_browser_autoplay(watch)
    return f"https://www.youtube.com/results?search_query={_up.quote_plus(query)}"


def yt_search_open_url(query: str) -> str:
    import urllib.parse as _up
    return f"https://www.youtube.com/results?search_query={_up.quote_plus(query)}"


def build_mpv_youtube_argv(
    yt_search: str,
    *,
    ipc_path: str,
    client: str = "",
) -> tuple[list[str], str]:
    """Build mpv argv for one YouTube play attempt. Returns (argv, target_label)."""
    target = f"ytdl://ytsearch1:{yt_search}"
    if yt_autoplay_enabled():
        mix = yt_mix_url(yt_resolve_watch_url(yt_search))
        if mix and "list=RD" in mix:
            target = mix
    cmd = [
        "mpv", target,
        f"--input-ipc-server={ipc_path}",
        "--no-video", "--really-quiet",
        "--ytdl-format=bestaudio/best",
    ]
    if "list=RD" in target:
        cmd.append("--ytdl-raw-options=yes-playlist=")
    if client:
        cmd.append(
            f"--ytdl-raw-options=extractor-args=youtube:player_client={client}"
        )
    cmd.append("--title=ELI-YouTube")
    label = client or "yt-dlp default"
    return cmd, label


def attempt_youtube_mpv(
    yt_search: str,
    *,
    ipc_path: str,
    verify_seconds: float | None = None,
) -> dict[str, Any]:
    """Try mpv playback with the yt-dlp client ladder. Returns a result dict."""
    if not (shutil.which("yt-dlp") and shutil.which("mpv")):
        return {
            "ok": False,
            "played": False,
            "reason": "missing_tools",
            "error": "mpv or yt-dlp not installed",
        }

    verify_s = float(verify_seconds if verify_seconds is not None
                      else os.environ.get("ELI_YT_VERIFY_SECONDS", "8.0"))
    err_log = None
    err_target: Any = subprocess.DEVNULL
    try:
        err_log = tempfile.NamedTemporaryFile(
            prefix="eli_mpv_", suffix=".log", delete=False, mode="w+",
        )
        err_target = err_log
    except Exception:
        log.debug("suppressed exception", exc_info=True)

    confirmed = False
    proc = None
    used_client = ""
    rc = None
    tail = ""

    for client in yt_player_clients():
        argv, used_client = build_mpv_youtube_argv(
            yt_search, ipc_path=ipc_path, client=client,
        )
        proc = subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=err_target, start_new_session=True,
        )
        deadline = time.monotonic() + max(0.0, verify_s)
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            if mpv_load_confirmed(ipc_path):
                confirmed = True
                break
            time.sleep(0.1)
        rc = proc.poll()
        if confirmed:
            break
        probe = ""
        if err_log is not None:
            try:
                err_log.flush()
                err_log.seek(0)
                probe = err_log.read()
            except Exception:
                log.debug("suppressed exception", exc_info=True)
        if rc is not None:
            try:
                from eli.integrations.media.cross_platform import mpv_ipc_send
                mpv_ipc_send(["quit"], sock_path=ipc_path, want_response=False)
            except Exception:
                pass
            if not yt_is_client_bound_failure(probe):
                break
        elif time.monotonic() >= deadline:
            break
        log.info(
            "[MEDIA] YouTube client %r refused for %r — trying next client",
            used_client, yt_search,
        )

    if err_log is not None:
        try:
            err_log.flush()
            err_log.seek(0)
            tail = err_log.read()
        except Exception:
            log.debug("suppressed exception", exc_info=True)

    if confirmed:
        if err_log is not None:
            try:
                err_log.close()
                os.unlink(err_log.name)
            except Exception:
                pass
        return {
            "ok": True,
            "played": True,
            "confirmed": True,
            "client": used_client,
            "ipc_path": ipc_path,
        }

    if rc is not None:
        direct_err = (
            "no match found on YouTube" if "empty playlist" in tail.lower()
            else "YouTube refused the stream for every player client I tried "
                 "(this usually means yt-dlp is out of date — upgrade yt-dlp)"
            if yt_is_client_bound_failure(tail)
            else "mpv could not start playback"
        )
        return {
            "ok": False,
            "played": False,
            "confirmed": False,
            "reason": "mpv_failed",
            "error": direct_err,
            "client": used_client,
            "rc": rc,
            "stderr_tail": tail[-2000:],
        }

    return {
        "ok": True,
        "played": False,
        "confirmed": False,
        "pending": True,
        "client": used_client,
        "ipc_path": ipc_path,
        "reason": "still_resolving",
    }
