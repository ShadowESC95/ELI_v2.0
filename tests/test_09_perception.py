"""
test_09_perception.py
=====================
Tests for eli.perception — STT, TTS, OS controller, analyzers, log rotation.
"""
import importlib
import pytest


def test_perception_package_init():
    assert importlib.import_module("eli.perception") is not None


def test_perception_audio_stt_loadable():
    assert importlib.import_module("eli.perception.audio_stt") is not None


def test_perception_tts_router_has_class():
    mod = importlib.import_module("eli.perception.tts_router")
    syms = dir(mod)
    matches = [s for s in syms if "TTS" in s or "Router" in s or "tts" in s.lower()]
    assert matches, f"No TTS router class: {syms}"


def test_perception_os_controller_loadable():
    assert importlib.import_module("eli.perception.os_controller") is not None


def test_perception_analyze_csv_loadable():
    assert importlib.import_module("eli.perception.analyze_csv") is not None


def test_perception_analyze_image_loadable():
    assert importlib.import_module("eli.perception.analyze_image") is not None


def test_perception_analyze_mesh_loadable():
    assert importlib.import_module("eli.perception.analyze_mesh") is not None


def test_perception_analyze_pdfs_loadable():
    assert importlib.import_module("eli.perception.analyze_pdfs") is not None


def test_perception_eli_listen_loadable():
    assert importlib.import_module("eli.perception.eli_listen") is not None


def test_perception_extract_equations_loadable():
    assert importlib.import_module("eli.perception.extract_equations") is not None


def test_perception_log_rotation_loadable():
    assert importlib.import_module("eli.perception.log_rotation") is not None


def test_perception_voice_worker_loadable():
    assert importlib.import_module("eli.perception.voice_worker") is not None


def test_perception_voice_worker_streaming_loadable():
    assert importlib.import_module("eli.perception.voice_worker_streaming") is not None
