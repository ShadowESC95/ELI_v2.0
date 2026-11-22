"""Tests for eli.perception.tts_router — ~100 tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import os
import pytest

from eli.perception.tts_router import (
    list_voices,
    find_voice_model,
    get_active_voice,
    set_active_voice,
    available_backends,
    _clean_text,
    _voice_dir,
    _DEFAULT_VOICE,
    _VOICE_SEARCH_DIRS,
    _is_system_voice,
    _run_tts,
    speak_if_enabled,
)


# ── Voice discovery ───────────────────────────────────────────────────────

def test_list_voices_returns_list():
    result = list_voices()
    assert isinstance(result, list)

def test_list_voices_at_least_three():
    result = list_voices()
    assert len(result) >= 3, f"Expected >=3 voices, got {result}"

def test_list_voices_are_strings():
    for v in list_voices():
        assert isinstance(v, str)

def test_list_voices_no_extension():
    for v in list_voices():
        assert not v.endswith(".onnx")

def test_list_voices_no_duplicates():
    voices = list_voices()
    assert len(voices) == len(set(voices))

def _installed_voices():
    """The Piper voices on this machine (the shipped set on CI, any added ones here)."""
    from eli.perception.tts_router import _voice_search_dirs
    return sorted({f.stem for d in _voice_search_dirs() for f in Path(d).glob("*.onnx")
                   if Path(str(f) + ".json").exists()})


def test_every_installed_voice_is_found_and_the_natural_ones_listed():
    """These tests named three high-quality voices that were only ever on the developer's machine;
    the release ships a smaller set. What holds anywhere: every installed voice is found, and every
    one that is not a robotic low-quality voice is offered."""
    installed = _installed_voices()
    if not installed:
        pytest.skip("no Piper voices installed")
    listed = list_voices()
    for name in installed:
        found = find_voice_model(name)
        assert found is not None and found.exists() and found.stem == name, name
        if not name.endswith("low"):
            assert name in listed, name


# ── Voice model finding ───────────────────────────────────────────────────

def test_find_voice_model_returns_path_or_none():
    result = find_voice_model("en_US-lessac-high")
    assert result is None or isinstance(result, Path)

def test_find_nonexistent_voice():
    result = find_voice_model("en_US-nonexistent-ultra")
    # Should fall back to any available voice or return None
    assert result is None or isinstance(result, Path)

def test_find_voice_model_onnx_extension():
    result = find_voice_model("en_US-lessac-high")
    if result:
        assert result.suffix == ".onnx"

def test_find_voice_env_override(monkeypatch, tmp_path):
    model = tmp_path / "custom.onnx"
    model.write_bytes(b"fake")
    monkeypatch.setenv("ELI_PIPER_MODEL", str(model))
    result = find_voice_model("en_US-ryan-high")
    assert result == model


# ── Active voice ──────────────────────────────────────────────────────────

def test_get_active_voice_returns_string():
    result = get_active_voice()
    assert isinstance(result, str)
    assert len(result) > 0

def test_get_active_voice_default(monkeypatch, tmp_path):
    """With NO override configured, the default must resolve to a real voice.

    Isolated deliberately. `get_active_voice()` reads process-wide mutable state —
    the ELI_PIPER_VOICE env var and the `tts_voice` key in whatever settings file
    is active — so asserting on it unisolated made this order-dependent: any test
    that had set a voice (SET_VOICE writes `char:calm`, for instance) decided the
    outcome, and it failed intermittently in the full suite while passing alone.
    Point it at an empty settings file and clear the env so this exercises the
    fallback chain it is actually named after.
    """
    monkeypatch.delenv("ELI_PIPER_VOICE", raising=False)
    settings = tmp_path / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(settings))

    result = get_active_voice()
    assert result in list_voices() or result == _DEFAULT_VOICE

def test_get_active_voice_env_override(monkeypatch):
    monkeypatch.setenv("ELI_PIPER_VOICE", "en_US-ryan-high")
    result = get_active_voice()
    assert result == "en_US-ryan-high"

def test_set_active_voice_changes_active(monkeypatch, tmp_path):
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(tmp_path / "settings.json"))
    set_active_voice("en_US-ryan-high")
    assert get_active_voice() == "en_US-ryan-high"


# ── available_backends ────────────────────────────────────────────────────

def test_available_backends_returns_dict():
    result = available_backends()
    assert isinstance(result, dict)

def test_available_backends_has_piper_python():
    result = available_backends()
    assert "piper_python" in result
    assert result["piper_python"] is True

def test_available_backends_has_piper_voices():
    result = available_backends()
    assert "piper_voices" in result
    assert isinstance(result["piper_voices"], list)

def test_available_backends_has_active_voice():
    result = available_backends()
    assert "active_voice" in result

def test_available_backends_has_active_model():
    result = available_backends()
    assert "active_model" in result

def test_available_backends_active_model_exists():
    result = available_backends()
    if result["active_model"]:
        assert Path(result["active_model"]).exists()


# ── _clean_text ───────────────────────────────────────────────────────────

def test_clean_text_strips_markdown():
    result = _clean_text("**bold** and _italic_ and `code`")
    assert "**" not in result
    assert "_" not in result
    assert "`" not in result

def test_clean_text_strips_headers():
    result = _clean_text("# Header\n## Sub")
    assert "#" not in result

def test_clean_text_collapses_whitespace():
    result = _clean_text("hello   world   there")
    assert "  " not in result

def test_clean_text_truncates_at_800():
    long_text = "word " * 200
    result = _clean_text(long_text)
    assert len(result) <= 800

def test_clean_text_empty_returns_empty():
    assert _clean_text("") == ""

def test_clean_text_none_returns_empty():
    assert _clean_text(None) == ""

def test_clean_text_whitespace_returns_empty():
    assert _clean_text("   ") == ""

def test_clean_text_strips_pipe():
    result = _clean_text("col1 | col2 | col3")
    assert "|" not in result

def test_clean_text_strips_gt():
    result = _clean_text("> blockquote")
    assert ">" not in result

def test_clean_text_preserves_content():
    result = _clean_text("The answer is 42")
    assert "answer" in result
    assert "42" in result


# ── speak_if_enabled ─────────────────────────────────────────────────────

def test_speak_if_enabled_false_does_not_speak():
    with patch("eli.perception.tts_router._run_tts") as mock_tts:
        speak_if_enabled("hello", enabled=False)
        mock_tts.assert_not_called()

def test_speak_if_enabled_true_calls_tts():
    with patch("eli.perception.tts_router._run_tts", return_value=True) as mock_tts:
        speak_if_enabled("hello", enabled=True)
        # Thread is async, but the function should return True
        # (thread is daemon so it won't block test)


def test_run_tts_speaks_more_than_three_chunks(monkeypatch):
    from eli.perception import tts_router

    spoken = []
    monkeypatch.setenv("ELI_TTS_CHUNK_CHARS", "25")
    monkeypatch.setattr(tts_router, "_speak_piper_cli", lambda chunk, voice_name=None: spoken.append(chunk) or True)

    text = "One short sentence. " * 12

    assert _run_tts(text, voice_name="test-voice")
    assert len(spoken) > 3


# ── Voice search dirs ─────────────────────────────────────────────────────

def test_voice_search_dirs_is_list():
    assert isinstance(_VOICE_SEARCH_DIRS, list)

def test_voice_dir_is_path():
    assert isinstance(_voice_dir(), Path)

def test_voice_dir_contains_models_tts_piper():
    assert "piper" in str(_voice_dir()) or "voices" in str(_voice_dir())

def test_voice_models_have_json_config():
    """Each .onnx should have a companion .onnx.json config."""
    for v in list_voices():
        model = find_voice_model(v)
        if model:
            config = model.parent / (model.name + ".json")
            assert config.exists(), f"Missing config for {v}: {config}"


# ── Default voice ─────────────────────────────────────────────────────────

def test_default_voice_constant():
    assert _DEFAULT_VOICE == "en_US-amy-medium"

def test_get_active_voice_resolves_to_usable_voice():
    result = get_active_voice()
    assert isinstance(result, str) and len(result) > 0
    if _is_system_voice(result):
        assert len(result) > len("sys:")
    else:
        from eli.runtime.voice_assets import piper_voice_ready
        if not piper_voice_ready(result):
            pytest.skip(f"the files of {result} are not on this box (setup downloads them; a clone has none)")
        assert result in list_voices() or find_voice_model(result) is not None


# ── Edge cases ────────────────────────────────────────────────────────────

def test_find_voice_empty_string():
    result = find_voice_model("")
    # Should fall back to any available voice
    assert result is None or isinstance(result, Path)

def test_find_voice_none():
    result = find_voice_model(None)
    assert result is None or isinstance(result, Path)

def test_list_voices_sorted():
    voices = list_voices()
    # Check voices list is consistent (same order each call)
    assert list_voices() == voices


# ── Never speak a degenerate fragment (also avoids piper wave crash) ──────────
import pytest as _pytest


@_pytest.mark.parametrize("frag", ["-", "-G", "-Auto", "-Auto/G 5/", "", "   ", "/ "])
def test_tts_refuses_unspeakable_fragment(frag):
    from eli.perception.tts_router import _eli_tts_is_unspeakable
    assert _eli_tts_is_unspeakable(frag) is True


@_pytest.mark.parametrize("ok", ["No.", "34G", "Volume down", "I'm ELI.",
                                 "Your first message was at 00:03:44 on 2026-06-06."])
def test_tts_speaks_real_short_text(ok):
    from eli.perception.tts_router import _eli_tts_is_unspeakable
    assert _eli_tts_is_unspeakable(ok) is False


def test_speaking_works_with_no_piper_program(monkeypatch, tmp_path):
    """The packaged app ships Piper's library and voices but no piper program; on a machine with no
    working piper program elsewhere ELI had no voice. With no program to run, the library speaks,
    a pause kept between sentences."""
    import io
    import sys
    import types
    import wave
    from eli.perception import tts_router as t

    calls = []

    class _Chunk:
        sample_rate, sample_width, sample_channels = 22050, 2, 1
        audio_int16_bytes = b"\x01\x00" * 22050          # one second

    class _Voice:
        @classmethod
        def load(cls, path, config_path=None):
            calls.append(("load", path))
            return cls()

        def synthesize(self, text, syn_config=None):
            calls.append(("say", text, getattr(syn_config, "kw", None)))
            return [_Chunk(), _Chunk()]

    class _Config:
        def __init__(self, **kw):
            self.kw = kw

    monkeypatch.setitem(sys.modules, "piper", types.SimpleNamespace(PiperVoice=_Voice, SynthesisConfig=_Config))
    monkeypatch.setattr(t, "_PIPER_LIB_VOICES", {})
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setattr(t, "find_voice_model", lambda name: model)
    monkeypatch.setattr(t, "_find_piper_config", lambda m: None)
    monkeypatch.setattr(t, "_find_piper_bin", lambda: None)
    monkeypatch.setattr(t, "_packaged_piper_binary_candidates", lambda: [])
    monkeypatch.delenv("ELI_PIPER_BINARY", raising=False)
    monkeypatch.delenv("ELI_PIPER_BIN", raising=False)
    monkeypatch.setenv("ELI_TTS_SPEAKING_LOCK", str(tmp_path / "speaking.lock"))
    played = []
    monkeypatch.setattr(t, "_play_wav_blocking", lambda wav: played.append(wav.read_bytes()) or True)

    assert t._speak_piper_cli("Hello there. A second sentence.") is True
    assert ("load", str(model)) in calls
    said = [c for c in calls if c[0] == "say"]
    assert said and said[0][2] and "length_scale" in said[0][2], "the program's prosody is not passed on"
    with wave.open(io.BytesIO(played[0])) as w:
        assert w.getnframes() > 2 * 22050, "no pause between the sentences"


def test_the_speaking_lock_is_held_for_the_whole_reply(tmp_path, monkeypatch):
    """Only Piper set it, and only per chunk: other voices, and the gaps between chunks, reached the mic."""
    import eli.perception.tts_router as tr
    lock = tmp_path / "speaking.lock"
    monkeypatch.setenv("ELI_TTS_SPEAKING_LOCK", str(lock))
    seen = []
    monkeypatch.setattr(tr, "_run_tts_impl", lambda text, voice_name=None: seen.append(lock.read_text()) or True)
    assert tr._run_tts("hello there", voice_name="any") is True
    assert seen == [str(os.getpid())] and not lock.exists()


# ── Playback goes through the desktop's sound server ─────────────────────────
def _tone_wav(path, rate=22050):
    import wave
    import numpy as np
    t = np.arange(rate // 2) / rate
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes((np.sin(2 * np.pi * 220 * t) * 12000).astype("<i2").tobytes())
    return path


def _portaudio(monkeypatch, devices, default_output=0, refuse=()):
    """A stand-in sounddevice listing `devices`; streams opened are recorded, none plays."""
    import sys
    import types

    class PortAudioError(Exception):
        pass

    opened = []

    class _Stream:
        def __init__(self, samplerate, channels, callback, device=None):
            name = devices[default_output if device is None else device]["name"]
            opened.append(name)
            if name in refuse:
                raise PortAudioError("Error opening OutputStream: Device unavailable [PaErrorCode -9985]")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def query_devices(device=None, kind=None):
        if kind == "output":
            return devices[default_output]
        return devices[device] if device is not None else list(devices)

    fake = types.SimpleNamespace(OutputStream=_Stream, PortAudioError=PortAudioError, CallbackStop=Exception,
                                 query_devices=query_devices, query_hostapis=lambda: [{"name": "ALSA"}],
                                 sleep=lambda ms: None)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return opened


def _dev(name, out=2):
    return {"name": name, "max_output_channels": out, "max_input_channels": 0,
            "default_samplerate": 48000.0, "hostapi": 0}


_CARDS_ONLY = [_dev("HDA Intel PCH: ALC1220 Analog (hw:0,0)", 6), _dev("HDA Intel PCH: ALC1220 Digital (hw:0,1)"),
               _dev("HDA NVidia: HDMI 0 (hw:1,3)", 8)]


def _player(monkeypatch, name="pw-play", amplitudes=None):
    """The system player stand-in: says which player played, plays nothing; meanwhile the
    lip-sync amplitude is recorded."""
    import time
    from eli.perception import tts_router
    from eli.cognition import expression_state
    played = []
    if amplitudes is not None:
        monkeypatch.setattr(expression_state, "set_amplitude", lambda v: amplitudes.append(float(v)))

    def _play(path, post_play_tail=None):
        played.append(str(path))
        time.sleep(0.15)                    # the player's own time: lip-sync runs meanwhile
        return name
    monkeypatch.setattr(tts_router, "_platform_play_wav", _play)
    return played


def test_speech_never_opens_a_sound_card_the_sound_server_holds(tmp_path, monkeypatch):
    """The AppImage's PortAudio listed only the cards, its default the raw "hw:0,0" PipeWire holds:
    opening it failed with "Device unavailable" while music played, and took the voice silently
    otherwise, while the log said every reply was spoken. With no device of the server's listed,
    the system player plays, through the server, and the voice's loudness still drives lip-sync."""
    from eli.perception import tts_router
    from eli.utils import platform_compat
    monkeypatch.setattr(platform_compat, "sound_server", lambda: "pipewire")
    opened = _portaudio(monkeypatch, _CARDS_ONLY)
    amps = []
    played = _player(monkeypatch, "pw-play", amps)

    result = tts_router._play_wav_blocking(_tone_wav(tmp_path / "v.wav"), post_play_tail=0)

    assert opened == [], f"a sound card the server holds was opened: {opened}"
    assert result and played
    assert "pw-play" in result.via
    assert max(amps) > 0.1 and amps[-1] == 0.0, "lip-sync got no loudness from the samples"
    assert tts_router.last_playback()["via"] == result.via


def test_speech_plays_on_the_sound_servers_own_portaudio_device(tmp_path, monkeypatch):
    from eli.perception import tts_router
    from eli.utils import platform_compat
    monkeypatch.setattr(platform_compat, "sound_server", lambda: "pipewire")
    devices = _CARDS_ONLY + [_dev("sysdefault", 128), _dev("pulse", 32), _dev("pipewire", 64), _dev("default", 64)]
    opened = _portaudio(monkeypatch, devices)
    played = _player(monkeypatch)

    result = tts_router._play_wav_blocking(_tone_wav(tmp_path / "v.wav"), post_play_tail=0)

    assert opened == ["pipewire"] and not played
    assert result and "pipewire" in result.via


def test_a_refused_server_device_falls_to_the_system_player_and_says_so(tmp_path, monkeypatch):
    from eli.perception import tts_router
    from eli.utils import platform_compat
    monkeypatch.setattr(platform_compat, "sound_server", lambda: "pulseaudio")
    opened = _portaudio(monkeypatch, _CARDS_ONLY + [_dev("pulse", 32)], refuse=("pulse",))
    played = _player(monkeypatch, "paplay")

    result = tts_router._play_wav_blocking(_tone_wav(tmp_path / "v.wav"), post_play_tail=0)

    assert opened == ["pulse"] and played
    assert result and "paplay" in result.via and "Device unavailable" in result.detail


def test_speech_that_could_not_be_played_is_reported_as_not_played(tmp_path, monkeypatch, caplog):
    """The log said "[TTS_FINAL_PIPER_ONLY] voice=… bytes=…" for every reply, heard or not."""
    import logging
    from eli.perception import tts_router
    from eli.utils import platform_compat
    monkeypatch.setattr(platform_compat, "sound_server", lambda: "pipewire")
    _portaudio(monkeypatch, _CARDS_ONLY)
    _player(monkeypatch, "")
    wav = _tone_wav(tmp_path / "v.wav")

    result = tts_router._play_wav_blocking(wav, post_play_tail=0)
    assert not result and "no system player" in result.detail
    with caplog.at_level(logging.WARNING, logger=tts_router.log.name):
        tts_router._log_played("[TTS_FINAL_PIPER_ONLY] voice=v", 1234, result)
    assert "NOT played" in caplog.text and "no system player" in caplog.text

    monkeypatch.setattr(tts_router, "_eli_tts_is_unspeakable", lambda text: False)
    monkeypatch.setattr(tts_router, "_speak_piper_cli", lambda chunk, voice=None: result)
    said = tts_router.speak_text("A reply that was never heard.")
    assert said["ok"] is False and "no system player" in said["error"]


def test_without_a_sound_server_portaudio_plays_on_its_default(tmp_path, monkeypatch):
    from eli.perception import tts_router
    from eli.utils import platform_compat
    monkeypatch.setattr(platform_compat, "sound_server", lambda: "")
    opened = _portaudio(monkeypatch, _CARDS_ONLY + [_dev("default", 64)], default_output=3)
    _player(monkeypatch)
    result = tts_router._play_wav_blocking(_tone_wav(tmp_path / "v.wav"), post_play_tail=0)
    assert opened == ["default"] and result


def test_the_sound_server_is_the_socket_a_client_would_reach(tmp_path, monkeypatch):
    """A session variable that names a socket which is not there is no server (the test run's own
    dead PULSE_SERVER / PIPEWIRE_REMOTE)."""
    import socket
    from eli.utils import platform_compat as pc
    if not pc.LINUX:
        pytest.skip("Linux sound servers")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("PIPEWIRE_REMOTE", str(tmp_path / "gone"))
    monkeypatch.setenv("PULSE_SERVER", "unix:" + str(tmp_path / "gone-too"))
    assert pc.sound_server() == ""
    s = socket.socket(socket.AF_UNIX)
    try:
        s.bind(str(tmp_path / "pipewire-0"))
        monkeypatch.delenv("PIPEWIRE_REMOTE")
        assert pc.sound_server() == "pipewire"
        monkeypatch.setattr(pc.shutil, "which", lambda name: f"/usr/bin/{name}")
        assert [p.rsplit("/", 1)[-1] for p in pc.wav_player_candidates()] == ["pw-play", "paplay", "aplay"]
    finally:
        s.close()
