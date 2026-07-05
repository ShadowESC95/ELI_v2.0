"""Flat GitHub asset restore (local-assets-v2.1 layout)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
RESTORE = SCRIPTS / "restore_github_asset_files.py"


def _load_restore():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("restore_github_asset_files", RESTORE)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def restore_mod():
    return _load_restore()


def test_flat_restore_places_gguf_and_skips_excluded_voices(tmp_path, restore_mod, monkeypatch):
    monkeypatch.setattr(restore_mod, "ROOT", tmp_path)
    download = tmp_path / "dl"
    download.mkdir()
    (download / "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf").write_bytes(b"gguf")
    (download / "nomic-embed-text-v1.5.Q4_K_M.gguf").write_bytes(b"embed")
    (download / "en_US-amy-medium.onnx").write_bytes(b"onnx")
    (download / "en_US-ryan-high.onnx").write_bytes(b"skip")
    (download / "en_US-lessac-high.onnx").write_bytes(b"skip")
    (download / "en_GB-cori-high.onnx").write_bytes(b"skip")

    count = restore_mod._restore_flat(download)

    assert count == 3
    assert (tmp_path / "models" / "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf").exists()
    assert (tmp_path / "models" / "embeddings" / "nomic-embed-text-v1.5.Q4_K_M.gguf").exists()
    assert (tmp_path / "tts_piper" / "piper" / "en_US-amy-medium.onnx").exists()
    assert not (tmp_path / "tts_piper" / "piper" / "en_US-ryan-high.onnx").exists()
    assert not (tmp_path / "tts_piper" / "piper" / "en_US-lessac-high.onnx").exists()
    assert not (tmp_path / "tts_piper" / "piper" / "en_GB-cori-high.onnx").exists()
