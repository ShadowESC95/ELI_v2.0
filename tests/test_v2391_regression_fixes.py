"""Regressions from live v2.3.91 session — dossier bloat, media routing, wake word."""
from __future__ import annotations

import inspect

from eli.execution import router_enhanced as router
from eli.integrations.media.spotify_intent import album_request
from eli.kernel.engine import CognitiveEngine, _phatic_time_authority_block
from eli.perception.audio_stt import VoiceGate


def _route(text: str) -> dict:
    fn = getattr(router, "route_command", None) or getattr(router, "route")
    return fn(text)


def test_youtube_com_not_spotify_for_song_by_artist():
    out = _route("play lion and thief by diabolic on youtube com")
    assert out["action"] == "PLAY_MEDIA"
    args = out.get("args") or {}
    assert args.get("target") == "youtube website"
    assert args.get("browser") is True
    assert "diabolic" in str(args.get("query") or "").lower()


def test_play_on_spotify_does_not_set_browser_flag():
    out = _route("play the watcher by dr dre on spotify")
    assert out["action"] == "PLAY_MEDIA"
    args = out.get("args") or {}
    assert args.get("target") == "spotify"
    assert not args.get("browser")


def test_lp_album_request_detected():
    assert album_request("marshall matters lp") == ("marshall matters", None)
    assert album_request("the martial matters lp") == ("martial matters", None)


def test_phatic_skips_orchestrator_again():
    src = inspect.getsource(CognitiveEngine.process)
    assert '_qclass != "PHATIC"' in src
    assert "_is_brief_phatic_prompt(user_input)" in src


def test_phatic_time_authority_present():
    block = _phatic_time_authority_block()
    assert "CURRENT TIME" in block
    assert "authoritative" in block.lower()


def test_trailing_wake_dispatches_safe_direct():
    gate = VoiceGate()
    kind, cmd, wake = gate.classify("pause. computer")
    assert kind == "dispatch"
    assert cmd == "pause"
    assert wake == "computer"
