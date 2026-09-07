"""Cross-platform media integrations (Spotify, mpv IPC, YouTube, capabilities)."""

from eli.integrations.media.capabilities import (
    detect_media_capabilities,
    detect_hardware_capabilities,
    media_capability_summary,
    platform_capability_report,
)
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
from eli.integrations.media.youtube_playback import (
    attempt_youtube_mpv,
    mpv_load_confirmed,
    yt_browser_play_url,
    yt_player_clients,
    yt_search_open_url,
)

__all__ = [
    "attempt_youtube_mpv",
    "detect_hardware_capabilities",
    "detect_media_capabilities",
    "platform_capability_report",
    "is_process_running",
    "media_capability_summary",
    "mpv_alive",
    "mpv_ipc_send",
    "mpv_load_confirmed",
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
    "yt_browser_play_url",
    "yt_player_clients",
    "yt_search_open_url",
]
