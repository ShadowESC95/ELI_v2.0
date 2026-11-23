"""
test_09_perception.py
=====================
Tests for eli.perception — STT, TTS, OS controller, analyzers, log rotation.
"""
import importlib
import pytest


def test_perception_tts_router_has_class():
    mod = importlib.import_module("eli.perception.tts_router")
    syms = dir(mod)
    matches = [s for s in syms if "TTS" in s or "Router" in s or "tts" in s.lower()]
    assert matches, f"No TTS router class: {syms}"


