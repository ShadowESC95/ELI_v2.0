"""
Media control plugin for ELI.
Thin wrapper that delegates to integrations/mpris/playerctl_backend.py

Handles: play, pause, stop, next, previous, volume, mute, status, list players
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from eli.plugins.base.base import Plugin


def _b():
    """Lazy import to avoid circular imports at startup."""
    from eli.integrations.mpris import playerctl_backend
    return playerctl_backend


class MediaPlugin(Plugin):
    name = "media"
    version = "1.0.0"
    description = "Controls media playback and system volume via MPRIS2/playerctl"
    requires = ["playerctl"]  # runtime dependency hint

    def __init__(self):
        # Plugin.execute()/register() rebind each handler via handler.__get__(self, ...),
        # which only works for an already-bound method (a plain lambda gets `self` injected
        # as its first arg on rebind and breaks) — so each action maps to a bound _act_*
        # adapter below, not a lambda, matching the other plugins' convention.
        self.actions = {
            "play": self._act_play,
            "pause": self._act_pause,
            "stop": self._act_stop,
            "play_pause": self._act_play_pause,
            "next_track": self._act_next_track,
            "previous_track": self._act_previous_track,
            "seek": self._act_seek,
            "get_volume": self._act_get_volume,
            "set_volume": self._act_set_volume,
            "mute": self._act_mute,
            "unmute": self._act_unmute,
            "toggle_mute": self._act_toggle_mute,
            "get_status": self._act_get_status,
            "list_players": self._act_list_players,
            "clipboard_set": self._act_clipboard_set,
            "clipboard_get": self._act_clipboard_get,
        }
        super().__init__()

    # ── Action adapters (args: dict -> the real, kwarg-based methods below) ────

    def _act_play(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.play(args.get("player"))

    def _act_pause(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.pause(args.get("player"))

    def _act_stop(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.stop(args.get("player"))

    def _act_play_pause(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.play_pause(args.get("player"))

    def _act_next_track(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.next_track(args.get("player"))

    def _act_previous_track(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.previous_track(args.get("player"))

    def _act_seek(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.seek(float(args.get("seconds") or 0), args.get("player"))

    def _act_get_volume(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.get_volume()

    def _act_set_volume(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.set_volume(int(args.get("level") or 0), args.get("player"))

    def _act_mute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.mute(bool(args.get("muted", True)))

    def _act_unmute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.unmute()

    def _act_toggle_mute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.toggle_mute()

    def _act_get_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.get_status(args.get("player"))

    def _act_list_players(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.list_players()

    def _act_clipboard_set(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.clipboard_set(args.get("text", ""))

    def _act_clipboard_get(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return self.clipboard_get()

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
