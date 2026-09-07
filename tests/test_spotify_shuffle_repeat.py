"""Shuffle/repeat media control tests."""
from eli.execution import executor_enhanced as ex


def test_shuffle_media_uses_cross_platform(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_shuffle",
        lambda p: calls.append(p) or {"ok": True, "content": "🔀 Shuffle on — spotify",
                                      "response": "🔀 Shuffle on — spotify"},
    )
    monkeypatch.setattr(ex, "_get_active_player", lambda: "spotify")
    out = ex.shuffle_media()
    assert out["action"] == "SHUFFLE_MEDIA"
    assert out["ok"] is True
    assert calls == ["spotify"]


def test_repeat_media_uses_cross_platform(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "eli.integrations.media.cross_platform.spotify_set_loop",
        lambda p: calls.append(p) or {"ok": True, "content": "🔁 Repeat track — spotify",
                                      "response": "🔁 Repeat track — spotify"},
    )
    monkeypatch.setattr(ex, "_get_active_player", lambda: "spotify")
    out = ex.repeat_media()
    assert out["action"] == "REPEAT_MEDIA"
    assert out["ok"] is True
    assert calls == ["spotify"]
