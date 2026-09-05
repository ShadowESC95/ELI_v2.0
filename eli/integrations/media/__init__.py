"""Cross-platform media integrations (Spotify, mpv IPC, process detection)."""

from eli.integrations.media.cross_platform import (
    is_process_running,
    mpv_alive,
    mpv_ipc_send,
    mpv_socket_path,
    spotify_clear_track_repeat,
    spotify_is_playing,
    spotify_launch_if_needed,
    spotify_live_meta,
    spotify_loop_status,
    spotify_open_uri,
    spotify_play,
    spotify_running,
    spotify_search,
    spotify_wait_playing,
    spotify_wait_running,
)

__all__ = [
    "is_process_running",
    "mpv_alive",
    "mpv_ipc_send",
    "mpv_socket_path",
    "spotify_clear_track_repeat",
    "spotify_is_playing",
    "spotify_launch_if_needed",
    "spotify_live_meta",
    "spotify_loop_status",
    "spotify_open_uri",
    "spotify_play",
    "spotify_running",
    "spotify_search",
    "spotify_wait_playing",
    "spotify_wait_running",
]
