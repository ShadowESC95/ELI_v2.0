"""Tone/emotion adaptor: two-system detection, empathetic autonomous policy,
override control, and the three output channels (text/voice/face) — all shading
ELI's delivery WITHOUT replacing his core personality.
"""
from __future__ import annotations

import pytest

from eli.cognition import emotion_palette as ep
from eli.cognition import tone_adaptor as ta


@pytest.fixture(autouse=True)
def _reset_tone():
    ta.clear_tone()
    ta.note_user_text("")
    yield
    ta.clear_tone()


# ── palette ───────────────────────────────────────────────────────────────────
def test_palette_is_rich_and_extensible():
    tones = ep.list_tones()
    for t in ("comedic", "professional", "street_smart", "deadpan", "sad", "ecstatic",
              "curious", "irritated", "gremlin", "tender", "neutral"):
        assert t in tones, t


@pytest.mark.parametrize("phrase,tone", [
    ("be comedic", "comedic"), ("talk street", "street_smart"),
    ("talk like a street kid", "street_smart"), ("go professional", "professional"),
    ("sound ecstatic", "ecstatic"), ("use a deadpan tone", "deadpan"),
    ("be a bit gremlin", "gremlin"), ("nonsense phrase", None),
])
def test_resolve_tone(phrase, tone):
    assert ep.resolve_tone(phrase) == tone


def test_user_can_add_a_tone(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "_tones_path", lambda: tmp_path / "tones.json")
    ep.all_tones(refresh=True)
    r = ep.add_tone("noir", {"desc": "shadowy", "text": "clipped, shadowy",
                             "voice": {"pitch": -2}, "expression": "brooding", "aliases": ["noir"]})
    assert r["ok"] and "noir" in ep.list_tones()


# ── two-system detection ──────────────────────────────────────────────────────
@pytest.mark.parametrize("text,emo", [
    ("this is so frustrating ugh", "irritated"),
    ("haha that's hilarious", "comedic"),
    ("I'm so excited let's go!!!", "ecstatic"),
    ("I don't understand what you mean", "confused"),
    ("yo bruh no cap", "street_smart"),
    ("per my last email, the deadline is Friday", "professional"),
])
def test_semantic_detection(text, emo):
    assert ta.detect_text_emotion(text)[0] == emo


# ── empathetic autonomous policy (respond, don't mirror) ──────────────────────
@pytest.mark.parametrize("user,expressed", [
    ("this is so frustrating ugh", "calm"),
    ("I'm heartbroken", "tender"),
    ("haha so funny", "playful"),
    ("I'm so excited!!!", "joyful"),
])
def test_autonomous_response_policy(user, expressed):
    ta.note_user_text(user)
    cur = ta.current_tone()
    assert cur["source"] == "auto" and cur["tone"] == expressed


def test_neutral_when_no_signal():
    ta.note_user_text("what time is it")
    assert ta.current_tone()["tone"] == "neutral"


# ── override wins ─────────────────────────────────────────────────────────────
def test_override_beats_detection():
    assert ta.set_tone("talk street")["tone"] == "street_smart"
    ta.note_user_text("I'm heartbroken")   # would otherwise → tender
    assert ta.current_tone()["tone"] == "street_smart"
    ta.clear_tone()
    ta.note_user_text("I'm heartbroken")
    assert ta.current_tone()["tone"] == "tender"


def test_set_tone_rejects_unknown():
    assert ta.set_tone("florblegorb")["ok"] is False


# ── the three output channels ─────────────────────────────────────────────────
def test_voice_prosody_changes_with_tone():
    ta.set_tone("sad")
    assert ta.voice_prosody()["length_scale"] > 1.1   # slow
    ta.set_tone("ecstatic")
    assert ta.voice_prosody()["length_scale"] < 1.0    # fast


def test_expression_channel():
    ta.set_tone("comedic")
    assert ta.expression() == "grinning"


def test_directive_preserves_core_personality():
    ta.set_tone("comedic")
    d = ta.text_directive().lower()
    assert "core personality" in d and "who you are" in d


def test_directive_empty_for_neutral():
    ta.clear_tone()
    ta.note_user_text("what time is it")
    assert ta.text_directive() == ""


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("ELI_TONE_ADAPT", "0")
    ta.note_user_text("I'm heartbroken")
    assert ta.current_tone()["tone"] == "neutral"


# ── registered as real actions ────────────────────────────────────────────────
def test_tone_actions_registered():
    import json
    from pathlib import Path
    m = json.loads((Path(__file__).resolve().parents[1] / "capability_manifest.json").read_text())
    by = {c["action"]: c for c in m["capabilities"]}
    for act in ("SET_TONE", "CLEAR_TONE"):
        assert act in by and by[act]["routable"], act


@pytest.mark.parametrize("text,action", [
    ("be comedic", "SET_TONE"), ("talk street", "SET_TONE"),
    ("go back to normal", "CLEAR_TONE"), ("be yourself", "CLEAR_TONE"),
    ("that joke was comedic gold", "CHAT"),  # passing mention must NOT switch tone
])
def test_tone_routing(text, action):
    from eli.execution.router_enhanced import route
    assert (route(text).get("action") or "").upper() == action
