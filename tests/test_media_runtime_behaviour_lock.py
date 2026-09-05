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


def test_youtube_play_delegates_to_original_executor():
    calls = []

    def original(action, args, *a, **kw):
        calls.append((action, args))
        return {"ok": True, "action": action, "content": "ORIGINAL", "response": "ORIGINAL"}

    execute_action = mr.install_media_executor(original)
    result = execute_action(
        "PLAY_MEDIA",
        {"target": "youtube", "query": "play youtube dr dre the watcher"},
    )

    assert calls == [
        ("PLAY_MEDIA", {"target": "youtube", "query": "play youtube dr dre the watcher"}),
    ]
    assert result["response"] == "ORIGINAL"


def test_pause_youtube_delegates_to_original_executor():
    calls = []

    def original(action, args, *a, **kw):
        calls.append((action, args))
        return {"ok": True, "action": action, "content": "⏸ Paused — YouTube",
                "response": "⏸ Paused — YouTube"}

    execute_action = mr.install_media_executor(original)
    result = execute_action("PAUSE_MEDIA", {"target": "youtube"})

    assert calls == [("PAUSE_MEDIA", {"target": "youtube"})]
    assert "Paused" in result["content"]


def test_spotify_play_delegates_to_original_executor():
    calls = []

    def original(action, args, *a, **kw):
        calls.append((action, args))
        return {"ok": True, "action": action, "content": "Playing on Spotify",
                "response": "Playing on Spotify"}

    execute_action = mr.install_media_executor(original)
    result = execute_action(
        "PLAY_MEDIA",
        {"target": "spotify", "query": "dmx"},
    )

    assert calls == [("PLAY_MEDIA", {"target": "spotify", "query": "dmx"})]
    assert result["response"] == "Playing on Spotify"
