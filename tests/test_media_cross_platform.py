"""Cross-platform media backend tests (mocked OS primitives)."""
from eli.integrations.media import cross_platform as cp


def test_is_process_running_linux_pgrep(monkeypatch):
    monkeypatch.setattr(cp.pc, "LINUX", True)
    monkeypatch.setattr(cp.pc, "MACOS", False)
    monkeypatch.setattr(cp.pc, "WINDOWS", False)
    monkeypatch.setattr(cp, "_run", lambda argv, **k: (True, "1234", ""))
    assert cp.is_process_running("spotify") is True


def test_spotify_open_uri_macos_uses_osascript(monkeypatch):
    monkeypatch.setattr(cp.pc, "LINUX", False)
    monkeypatch.setattr(cp.pc, "MACOS", True)
    monkeypatch.setattr(cp.pc, "WINDOWS", False)
    calls = []
    monkeypatch.setattr(cp, "_macos_osascript", lambda s: calls.append(s) or (True, ""))
    assert cp.spotify_open_uri("spotify:search:test") is True
    assert calls and "open location" in calls[0]


def test_mpv_apply_browser_autoplay_from_executor():
    from eli.execution.executor_enhanced import _yt_apply_browser_autoplay, _yt_mix_url
    mix = _yt_mix_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    url = _yt_apply_browser_autoplay(mix)
    assert "autoplay=1" in url
    assert "start_radio=1" in url


def test_mpv_ipc_send_unix_socket(monkeypatch, tmp_path):
    sock = tmp_path / "mpv.sock"

    class _Sock:
        def __init__(self, *a, **k):
            self._buf = b""

        def settimeout(self, _t):
            return None

        def connect(self, _p):
            return None

        def sendall(self, data):
            self._buf = data

        def recv(self, _n):
            return b'{"data": 123.0}\n'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(cp.os.path, "exists", lambda p: True)
    monkeypatch.setattr(cp, "_is_windows_pipe", lambda _p: False)
    import socket as _socket
    monkeypatch.setattr(_socket, "socket", lambda *a, **k: _Sock())

    out = cp.mpv_ipc_send(["get_property", "duration"], sock_path=str(sock), want_response=True)
    assert out == 123.0


def test_spotify_search_type_and_play_drives_real_search_box(monkeypatch):
    """The scrape-based resolvers return nothing against the real site (its
    search page is a JS shell with no server-rendered track data) — this is
    the real mechanism: type into Spotify's own search and play the top hit,
    using its documented Ctrl+L shortcut then Down+Enter. Reuses the existing,
    already Wayland/pyautogui-aware key_press/type_text in platform_compat
    rather than a second, Linux-only input layer."""
    monkeypatch.setattr(cp, "spotify_launch_if_needed", lambda: True)
    monkeypatch.setattr(cp, "spotify_wait_running", lambda timeout=8.0: True)
    monkeypatch.setattr(cp, "spotify_play", lambda: True)
    monkeypatch.setattr(cp, "track_query_matches_now_playing", lambda query, player="spotify": True)
    monkeypatch.setattr(cp.time, "sleep", lambda _s: None)

    calls = []
    import eli.system.portable_app_control as pac
    import eli.utils.platform_compat as platc
    monkeypatch.setattr(pac, "focus_app", lambda name: calls.append(("focus", name)))
    monkeypatch.setattr(pac, "active_window_matches", lambda name: True)
    monkeypatch.setattr(pac, "window_exists", lambda name: True)
    monkeypatch.setattr(platc, "key_press", lambda keys: calls.append(("key", keys)) or True)
    monkeypatch.setattr(platc, "type_text", lambda text: calls.append(("type", text)) or True)

    assert cp.spotify_search_type_and_play("soldiers logic by diabolic") is True
    assert ("key", "ctrl+l") in calls
    assert ("type", "soldiers logic by diabolic") in calls
    assert calls.index(("key", "ctrl+l")) < calls.index(("type", "soldiers logic by diabolic"))
    assert ("key", "Down") in calls
    assert ("key", "Return") in calls
    assert calls.index(("key", "Return")) > calls.index(("key", "Down"))


def test_spotify_search_type_and_play_false_when_search_shortcut_unavailable(monkeypatch):
    """No native input tool and no pyautogui means key_press itself returns
    False — the caller must bail rather than type into whatever has focus."""
    monkeypatch.setattr(cp, "spotify_launch_if_needed", lambda: True)
    monkeypatch.setattr(cp, "spotify_wait_running", lambda timeout=8.0: True)
    monkeypatch.setattr(cp.time, "sleep", lambda _s: None)
    import eli.system.portable_app_control as pac
    import eli.utils.platform_compat as platc
    monkeypatch.setattr(pac, "focus_app", lambda name: None)
    monkeypatch.setattr(pac, "active_window_matches", lambda name: True)
    monkeypatch.setattr(pac, "window_exists", lambda name: True)
    monkeypatch.setattr(platc, "key_press", lambda keys: False)
    assert cp.spotify_search_type_and_play("anything") is False


def test_spotify_search_type_and_play_refuses_to_type_without_confirmed_focus(monkeypatch):
    """Regression: focus_app() reporting success ("I raised the window") is not
    the same as Spotify actually having input focus. A prior build trusted it
    blindly and sent a real user's play request straight into ELI's own chat
    box instead of Spotify. No keystroke may be sent unless
    active_window_matches() independently confirms focus first."""
    monkeypatch.setattr(cp, "spotify_launch_if_needed", lambda: True)
    monkeypatch.setattr(cp, "spotify_wait_running", lambda timeout=8.0: True)
    monkeypatch.setattr(cp.time, "sleep", lambda _s: None)

    calls = []
    import eli.system.portable_app_control as pac
    import eli.utils.platform_compat as platc
    monkeypatch.setattr(pac, "focus_app", lambda name: {"ok": True})
    monkeypatch.setattr(pac, "active_window_matches", lambda name: False)
    monkeypatch.setattr(pac, "window_exists", lambda name: True)
    monkeypatch.setattr(platc, "key_press", lambda keys: calls.append(("key", keys)) or True)
    monkeypatch.setattr(platc, "type_text", lambda text: calls.append(("type", text)) or True)

    assert cp.spotify_search_type_and_play("gangsters paradise by coolio") is False
    assert calls == []


def test_spotify_search_type_and_play_aborts_if_focus_lost_before_typing(monkeypatch):
    """Focus can be confirmed right after focus_app() and still be gone a beat
    later (another window steals it). Re-checked right before type_text()."""
    monkeypatch.setattr(cp, "spotify_launch_if_needed", lambda: True)
    monkeypatch.setattr(cp, "spotify_wait_running", lambda timeout=8.0: True)
    monkeypatch.setattr(cp.time, "sleep", lambda _s: None)

    import itertools
    focus_checks = itertools.cycle([True, False])  # confirmed, then lost — every attempt
    typed = []
    import eli.system.portable_app_control as pac
    import eli.utils.platform_compat as platc
    monkeypatch.setattr(pac, "focus_app", lambda name: {"ok": True})
    monkeypatch.setattr(pac, "active_window_matches", lambda name: next(focus_checks))
    monkeypatch.setattr(pac, "window_exists", lambda name: True)
    monkeypatch.setattr(platc, "key_press", lambda keys: True)
    monkeypatch.setattr(platc, "type_text", lambda text: typed.append(text) or True)

    assert cp.spotify_search_type_and_play("gangsters paradise by coolio") is False
    assert typed == []


def test_spotify_search_type_and_play_false_when_launch_fails(monkeypatch):
    monkeypatch.setattr(cp, "spotify_launch_if_needed", lambda: False)
    assert cp.spotify_search_type_and_play("anything") is False


def test_spotify_search_type_and_play_does_not_claim_success_without_metadata_match(monkeypatch):
    """Regression (live session, 2026-10-01): "play eminem trouble on spotify"
    sent Ctrl+L, typed, Down, Enter with no refusal logged — but only opened
    the search page and played nothing. Spotify's search suggestions are a
    live, debounced network call; Down+Enter can fire before they populate
    and select nothing. spotify_play() still reports "Playing" (whatever was
    already queued resumes), so success must be gated on the live track
    actually matching the request, not just the transport status."""
    monkeypatch.setattr(cp, "spotify_launch_if_needed", lambda: True)
    monkeypatch.setattr(cp, "spotify_wait_running", lambda timeout=8.0: True)
    monkeypatch.setattr(cp, "spotify_play", lambda: True)
    monkeypatch.setattr(cp, "track_query_matches_now_playing", lambda query, player="spotify": False)
    monkeypatch.setattr(cp.time, "sleep", lambda _s: None)

    import eli.system.portable_app_control as pac
    import eli.utils.platform_compat as platc
    monkeypatch.setattr(pac, "focus_app", lambda name: {"ok": True})
    monkeypatch.setattr(pac, "active_window_matches", lambda name: True)
    monkeypatch.setattr(pac, "window_exists", lambda name: True)
    monkeypatch.setattr(platc, "key_press", lambda keys: True)
    monkeypatch.setattr(platc, "type_text", lambda text: True)

    assert cp.spotify_search_type_and_play("eminem trouble") is False


def test_spotify_search_type_and_play_retries_once_then_succeeds(monkeypatch):
    """The first pass can lose the race against Spotify's search suggestions;
    a second full pass (re-focus, re-open search, re-type) gets a fresh shot
    rather than blindly re-pressing Down+Enter into an unknown UI state."""
    monkeypatch.setattr(cp, "spotify_launch_if_needed", lambda: True)
    monkeypatch.setattr(cp, "spotify_wait_running", lambda timeout=8.0: True)
    monkeypatch.setattr(cp, "spotify_play", lambda: True)
    monkeypatch.setattr(cp.time, "sleep", lambda _s: None)

    match_results = iter([False, True])  # first attempt loses the race, second confirms
    monkeypatch.setattr(cp, "track_query_matches_now_playing",
                         lambda query, player="spotify": next(match_results))

    import eli.system.portable_app_control as pac
    import eli.utils.platform_compat as platc
    monkeypatch.setattr(pac, "focus_app", lambda name: {"ok": True})
    monkeypatch.setattr(pac, "active_window_matches", lambda name: True)
    monkeypatch.setattr(pac, "window_exists", lambda name: True)
    type_calls = []
    monkeypatch.setattr(platc, "key_press", lambda keys: True)
    monkeypatch.setattr(platc, "type_text", lambda text: type_calls.append(text) or True)

    assert cp.spotify_search_type_and_play("eminem trouble") is True
    assert type_calls == ["eminem trouble", "eminem trouble"], "must re-type on retry, not just re-press Enter"


def test_track_query_matches_now_playing_true_on_token_overlap(monkeypatch):
    monkeypatch.setattr(cp, "spotify_live_meta",
                         lambda player="spotify": ("▶ Playing", "Eminem", "Trouble"))
    assert cp.track_query_matches_now_playing("eminem trouble") is True
    assert cp.track_query_matches_now_playing("trouble by eminem") is True


def test_track_query_matches_now_playing_false_on_unrelated_track(monkeypatch):
    monkeypatch.setattr(cp, "spotify_live_meta",
                         lambda player="spotify": ("▶ Playing", "Immortal Technique", "Point Of No Return"))
    assert cp.track_query_matches_now_playing("evil by eminem") is False


def test_track_query_matches_now_playing_false_when_nothing_live(monkeypatch):
    monkeypatch.setattr(cp, "spotify_live_meta", lambda player="spotify": ("", "", ""))
    assert cp.track_query_matches_now_playing("evil by eminem") is False
