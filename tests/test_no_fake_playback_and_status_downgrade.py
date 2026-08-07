"""Locks for two defects that made ELI state things that were not true.

1. PLAY_MEDIA on YouTube reported `played: True` the instant mpv was *spawned*, so a
   track that never started was announced as playing (and stderr went to DEVNULL, so
   the reason was unrecoverable afterwards).
2. NOW_PLAYING — a live-state read — was classified as a "soft informational" action
   and silently downgraded to CHAT whenever bus grounding was low. A state query has
   no memory grounding by nature, so the downgrade fired every time and handed the
   question to the model, which invented an answer instead of reporting the truth.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from eli.execution import executor_enhanced as ex
from eli.kernel.engine import _is_soft_informational_action

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── 1. Live-state actions must never be downgraded to CHAT ──────────────────
def _manifest_actions() -> set[str]:
    data = json.loads((REPO_ROOT / "capability_manifest.json").read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else (
        data.get("capabilities") or data.get("actions") or data
    )
    if isinstance(entries, dict):
        return {str(k).upper() for k in entries}
    names = set()
    for e in entries:
        n = (e.get("action") or e.get("name") or e.get("id")) if isinstance(e, dict) else e
        if n:
            names.add(str(n).upper())
    return names


def test_now_playing_is_never_downgraded():
    """The exact action from the live transcript where ELI confabulated."""
    assert _is_soft_informational_action("NOW_PLAYING") is False


@pytest.mark.parametrize("action", sorted(
    a for a in _manifest_actions()
    if re.search(r"(STATUS|_STATS|_USAGE)$", a) or a == "NOW_PLAYING"
))
def test_every_live_state_action_is_exempt(action):
    """Guards against the enumeration drifting again — this list is derived from the
    shipped manifest, so a newly added *_STATUS action is covered automatically."""
    assert _is_soft_informational_action(action) is False, (
        f"{action} reads live state; downgrading it to CHAT makes ELI guess "
        f"instead of reporting what is actually true."
    )


@pytest.mark.parametrize("action", ["REFRESH_USER_INFO", "SUMMARIZE", "EXPLAIN_TOPIC"])
def test_synthesised_actions_stay_downgradeable(action):
    """The downgrade must keep working for what it was built for."""
    assert _is_soft_informational_action(action) is True


@pytest.mark.parametrize("action", ["PLAY_MEDIA", "VOLUME", "OPEN_APP", "CHAT", "GET_TIME"])
def test_control_actions_stay_exempt(action):
    assert _is_soft_informational_action(action) is False


# ── 2. YouTube playback must be verified before it is claimed ───────────────
# `play_specific` does `import subprocess as _sp` inside the function, so the
# alias is the real module object — patching subprocess.Popen is what it sees.
class _FakeProc:
    """mpv stand-in. `rc=None` = still running; an int = exited with that code."""

    def __init__(self, rc):
        self._rc = rc
        self.pid = 4242

    def poll(self):
        return self._rc

    # Patching subprocess.Popen globally means subprocess.run() picks this up too
    # (via _resolve_media_target); support the context manager so it fails quietly.
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


@pytest.fixture
def _yt_env(monkeypatch):
    """Pin the YouTube branch: tools present, no real network, no real browser."""
    monkeypatch.setattr(ex.shutil, "which", lambda c: f"/usr/bin/{c}"
                        if c in ("mpv", "yt-dlp") else None)
    monkeypatch.setattr(ex, "_mpv_quit", lambda: None)
    monkeypatch.setattr(ex, "_set_now_playing", lambda *a, **k: None)
    monkeypatch.setattr(ex, "_mpv_ipc", lambda *a, **k: None)
    opened: list[str] = []
    monkeypatch.setattr(ex, "_open_in_browser", lambda url: opened.append(url))
    monkeypatch.setattr(ex, "_yt_resolve_watch_url", lambda q: "https://youtu.be/stub")
    monkeypatch.setattr(ex, "_yt_mix_url", lambda u: u)
    monkeypatch.setenv("ELI_YT_VERIFY_SECONDS", "0.3")   # keep the test fast
    return opened


def test_dead_mpv_is_not_reported_as_playing(monkeypatch, _yt_env):
    """The core regression: mpv exits immediately, so nothing is playing."""
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProc(rc=2))

    result = ex.play_specific("some track", target="youtube")

    assert result.get("played") is not True
    assert "Playing" not in (result.get("response") or "")


def test_dead_mpv_falls_back_honestly(monkeypatch, _yt_env):
    """A failed spawn degrades to the browser and says so — no silent success."""
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProc(rc=2))

    result = ex.play_specific("some track", target="youtube")

    assert _yt_env, "should have fallen back to opening the browser"
    assert "direct playback failed" in (result.get("response") or "")


def test_failure_message_stays_speakable(monkeypatch, _yt_env):
    """`response` is read aloud by TTS — raw mpv stderr must not leak into it."""
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProc(rc=2))

    response = ex.play_specific("some track", target="youtube").get("response") or ""

    for noise in ("ytdl_hook", "Traceback", "protocol handler", "compile-time"):
        assert noise not in response
    assert len(response) < 300


def test_confirmed_load_is_reported_as_playing(monkeypatch, _yt_env):
    """The happy path must still claim playback — the fix must not make ELI mute.

    "Confirmed" means mpv reported a duration, i.e. yt-dlp resolved the URL and the
    demuxer opened the stream. That, not mere liveness, is what licenses "Playing".
    """
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProc(rc=None))
    monkeypatch.setattr(ex, "_mpv_load_confirmed", lambda _sock: True)

    result = ex.play_specific("some track", target="youtube")

    assert result.get("played") is True
    assert "Playing" in (result.get("response") or "")


def test_alive_but_unloaded_mpv_is_not_claimed_as_playing(monkeypatch, _yt_env):
    """The slow-failure gap: a yt-dlp resolve that is still grinding stays ALIVE for
    seconds before it exits. Liveness alone would report that as playing — the original
    defect in slower clothing. Nothing loaded means nothing is claimed."""
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProc(rc=None))
    monkeypatch.setattr(ex, "_mpv_load_confirmed", lambda _sock: False)

    result = ex.play_specific("some track", target="youtube")

    assert result.get("played") is not True
    assert result.get("pending") is True
    response = result.get("response") or ""
    assert "not confirmed" in response.lower() or "still resolving" in response.lower()


def test_mpv_stderr_is_not_discarded(monkeypatch, _yt_env):
    """DEVNULL on stderr is what made the original failure un-diagnosable."""
    captured = {}

    def _spy(argv, *a, **k):
        captured["stderr"] = k.get("stderr")
        return _FakeProc(rc=2)

    monkeypatch.setattr(subprocess, "Popen", _spy)
    ex.play_specific("some track", target="youtube")

    assert captured["stderr"] is not subprocess.DEVNULL
    assert hasattr(captured["stderr"], "write"), "stderr must go somewhere readable"
