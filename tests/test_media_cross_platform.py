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
