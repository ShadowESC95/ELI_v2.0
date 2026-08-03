"""Voice-library actions are real routable capabilities, not just GUI buttons.

Before this, the 166-voice download library was reachable only from Settings ▸ Voice;
a user could not ask ELI to list/download/switch voices by voice or text.
"""
from __future__ import annotations

import pytest

from eli.execution.router_enhanced import route
from eli.runtime import voice_assets as va


def _action(text: str) -> str:
    return (route(text).get("action") or "").upper()


# ── routing ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "what voices do you have", "list voices", "which accents can I get",
    "show me the available voices",
])
def test_list_voices_routes(text):
    assert _action(text) == "LIST_VOICES"


@pytest.mark.parametrize("text", [
    "download a British voice", "get me a Scottish accent",
    "install en_US-amy-medium", "download en_GB-alan-medium",
    "get an american voice", "add a french voice",
])
def test_download_voice_routes(text):
    assert _action(text) == "DOWNLOAD_VOICE"


@pytest.mark.parametrize("text", [
    "use the alan voice", "switch your voice to amy", "use the calm voice",
])
def test_set_voice_routes(text):
    assert _action(text) == "SET_VOICE"


@pytest.mark.parametrize("text", [
    "use a funny voice", "use a serious voice", "be more formal",
    "change your voice to sarcastic",
])
def test_tone_requests_go_to_the_tone_system_not_a_voice_switch(text):
    """A named emotion/tone ('funny'→comedic, 'formal'→professional) must reach the
    richer SET_TONE (shades delivery), never a TTS-voice switch/download."""
    assert _action(text) == "SET_TONE"


@pytest.mark.parametrize("text", [
    "speak to me like a pirate", "talk to me like a wise old wizard",
])
def test_freetext_persona_style_stays_persona(text):
    """A free-text style that isn't a palette tone stays SET_COMMUNICATION_STYLE."""
    assert _action(text) == "SET_COMMUNICATION_STYLE"


def test_install_firefox_is_not_a_voice_download():
    assert _action("install firefox") != "DOWNLOAD_VOICE"


# ── resolver ────────────────────────────────────────────────────────────────
def test_resolve_voice_query_kinds():
    assert va.resolve_voice_query("install en_US-amy-medium")["voice"] == "en_US-amy-medium"
    assert va.resolve_voice_query("use the calm voice")["voice"] == "char:calm"
    assert va.resolve_voice_query("a British voice")["kind"] == "accent"
    assert va.resolve_voice_query("something sarcastic")["voice"] == ""


def test_resolve_accent_hint_uses_word_boundaries():
    """'us' must not match inside 'use' (the 'use a funny voice' regression)."""
    assert va.resolve_voice_query("use a funny voice")["voice"] == ""
    assert va.resolve_voice_query("a us voice")["kind"] == "accent"


# ── execution ───────────────────────────────────────────────────────────────
def test_list_voices_executes():
    from eli.execution.executor_enhanced import execute
    r = execute("LIST_VOICES", {})
    assert r.get("ok") and "voice" in r.get("content", "").lower()


def test_set_voice_executes_and_restores(monkeypatch):
    from eli.execution.executor_enhanced import execute
    from eli.perception import tts_router
    prev = tts_router.get_active_voice()
    try:
        r = execute("SET_VOICE", {"query": "use the calm voice"})
        assert r.get("ok") and r.get("voice") == "char:calm"
    finally:
        tts_router.set_active_voice(prev)


def test_download_voice_unresolvable_is_honest():
    from eli.execution.executor_enhanced import execute
    r = execute("DOWNLOAD_VOICE", {"query": "zzz nonsense qqq"})
    assert r.get("ok") is False
    assert "couldn't tell which voice" in r.get("content", "").lower()


def test_new_actions_are_registered_capabilities():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    m = json.loads((root / "capability_manifest.json").read_text(encoding="utf-8"))
    by = {c["action"]: c for c in m["capabilities"]}
    for a in ("LIST_VOICES", "DOWNLOAD_VOICE", "SET_VOICE"):
        assert a in by, f"{a} missing from manifest"
        assert by[a].get("routable") and by[a].get("in_dispatch")
