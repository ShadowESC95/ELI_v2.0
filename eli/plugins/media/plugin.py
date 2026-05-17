"""
Media control plugin for ELI.
Thin wrapper that delegates to integrations/mpris/playerctl_backend.py

Handles: play, pause, stop, next, previous, volume, mute, status, list players
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _b():
    """Lazy import to avoid circular imports at startup."""
    from eli.integrations.mpris import playerctl_backend
    return playerctl_backend


class MediaPlugin:
    name = "media"
    version = "1.0.0"
    description = "Controls media playback and system volume via MPRIS2/playerctl"
    requires = ["playerctl"]  # runtime dependency hint

    # ── Playback ──────────────────────────────────────────────

    def play(self, player: Optional[str] = None) -> Dict[str, Any]:
        return _b().play(player)

    def pause(self, player: Optional[str] = None) -> Dict[str, Any]:
        return _b().pause(player)

    def stop(self, player: Optional[str] = None) -> Dict[str, Any]:
        """Stop playback (Spotify → pause, others → stop)."""
        return _b().stop(player)

    def play_pause(self, player: Optional[str] = None) -> Dict[str, Any]:
        return _b().play_pause(player)

    def next_track(self, player: Optional[str] = None) -> Dict[str, Any]:
        return _b().next_track(player)

    def previous_track(self, player: Optional[str] = None) -> Dict[str, Any]:
        return _b().previous_track(player)

    def seek(self, seconds: float, player: Optional[str] = None) -> Dict[str, Any]:
        return _b().seek(seconds, player)

    # ── Volume ────────────────────────────────────────────────

    def get_volume(self) -> Dict[str, Any]:
        return _b().get_volume()

    def set_volume(self, level: int, player: Optional[str] = None) -> Dict[str, Any]:
        return _b().set_volume(level, player)

    def mute(self, muted: bool = True) -> Dict[str, Any]:
        return _b().mute(muted)

    def unmute(self) -> Dict[str, Any]:
        return _b().unmute()

    def toggle_mute(self) -> Dict[str, Any]:
        return _b().toggle_mute()

    # ── Status ────────────────────────────────────────────────

    def get_status(self, player: Optional[str] = None) -> Dict[str, Any]:
        return _b().get_player_status(player)

    def list_players(self) -> Dict[str, Any]:
        players = _b().list_players()
        msg = ", ".join(players) if players else "No media players running"
        return {"ok": True, "players": players, "content": msg, "response": msg}

    # ── Clipboard ─────────────────────────────────────────────

    def clipboard_set(self, text: str) -> Dict[str, Any]:
        return _b().clipboard_set(text)

    def clipboard_get(self) -> Dict[str, Any]:
        return _b().clipboard_get()


# ── Singleton ─────────────────────────────────────────────────

_plugin: Optional[MediaPlugin] = None


def get_plugin() -> MediaPlugin:
    global _plugin
    if _plugin is None:
        _plugin = MediaPlugin()
    return _plugin
