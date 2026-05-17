from eli.execution import media_runtime as mr


class _RunResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _PopenResult:
    pass


def test_noop_returns_message_without_original_executor():
    calls = []

    def original(*args, **kwargs):
        calls.append((args, kwargs))
        return "ORIGINAL"

    execute_action = mr.install_media_executor(original)

    assert execute_action("NOOP", {"message": "Say what to play."}) == "Say what to play."
    assert calls == []


def test_youtube_query_uses_mpv_search_and_cleans_leaked_words(monkeypatch):
    popen_calls = []

    def fake_which(cmd):
        if cmd == "mpv":
            return f"/usr/bin/{cmd}"
        return None

    def fake_popen(argv, *args, **kwargs):
        popen_calls.append(argv)
        return _PopenResult()

    monkeypatch.setattr(mr.shutil, "which", fake_which)
    monkeypatch.setattr(mr.os.path, "exists", lambda _path: False)
    monkeypatch.setattr(mr.subprocess, "Popen", fake_popen)

    execute_action = mr.install_media_executor(lambda *a, **k: "ORIGINAL")
    result = execute_action(
        "PLAY_MEDIA",
        {"target": "youtube", "query": "play youtube dr dre the watcher"},
    )

    assert result == "YouTube: playing first result via mpv: dr dre the watcher"
    assert popen_calls, "mpv was not invoked"
    assert "ytdl://ytsearch1:dr dre the watcher" in popen_calls[-1]
    assert all("play youtube" not in str(part) for part in popen_calls[-1])


def test_pause_youtube_targets_mpv_not_original_executor(monkeypatch):
    calls = []
    run_calls = []

    def original(*args, **kwargs):
        calls.append((args, kwargs))
        return "ORIGINAL"

    def fake_which(cmd):
        if cmd == "playerctl":
            return "/usr/bin/playerctl"
        return None

    def fake_run(argv, *args, **kwargs):
        run_calls.append(argv)
        return _RunResult(returncode=0)

    monkeypatch.setattr(mr.shutil, "which", fake_which)
    monkeypatch.setattr(mr.os.path, "exists", lambda _path: False)
    monkeypatch.setattr(mr.subprocess, "run", fake_run)

    execute_action = mr.install_media_executor(original)
    result = execute_action("PAUSE_MEDIA", {"target": "youtube"})

    assert result == "⏸ Paused — mpv"
    assert ["playerctl", "-p", "mpv", "pause"] in run_calls
    assert calls == []


def test_spotify_query_uses_spotify_runtime_not_original_executor(monkeypatch):
    calls = []
    run_calls = []
    popen_calls = []

    def original(*args, **kwargs):
        calls.append((args, kwargs))
        return "ORIGINAL"

    def fake_which(cmd):
        if cmd in {"dbus-send", "playerctl", "spotify"}:
            return f"/usr/bin/{cmd}"
        return None

    def fake_run(argv, *args, **kwargs):
        run_calls.append(argv)
        return _RunResult(returncode=0)

    def fake_popen(argv, *args, **kwargs):
        popen_calls.append(argv)
        return _PopenResult()

    monkeypatch.setattr(mr.shutil, "which", fake_which)
    monkeypatch.setattr(mr.subprocess, "run", fake_run)
    monkeypatch.setattr(mr.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(mr.time, "sleep", lambda _seconds: None)

    execute_action = mr.install_media_executor(original)
    result = execute_action("PLAY_MEDIA", {"target": "spotify", "query": "dmx"})

    assert result == "Searching Spotify for: dmx"
    assert popen_calls and popen_calls[0] == ["spotify"]
    assert any(call[:3] == ["playerctl", "-p", "spotify"] for call in run_calls)
    assert calls == []
