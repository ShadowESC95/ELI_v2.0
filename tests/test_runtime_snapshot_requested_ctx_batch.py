"""The runtime snapshot must record the operator's requested ctx/batch separately from
what loaded, so a fallback is not reported as \"loaded as requested\"."""
from __future__ import annotations

import json

import pytest

try:
    from PySide6.QtWidgets import QApplication
    if type(QApplication).__name__ == "MagicMock":
        raise RuntimeError("PySide6 mocked")
    from eli.gui.eli_pro_audio_gui_v2_0 import LocalModelManager
except Exception as _e:  # pragma: no cover
    pytest.skip(f"needs real PySide6 ({_e}); run with --noconftest", allow_module_level=True)


def _write(tmp_path, monkeypatch, **kwargs):
    from eli.core import paths as paths_mod

    class _Paths:
        artifacts_dir = tmp_path

    monkeypatch.setattr(paths_mod, "get_paths", lambda: _Paths())
    mgr = LocalModelManager()
    mgr.n_batch = kwargs.pop("n_batch_attr", 0)
    mgr.is_loaded = True
    mgr._write_shared_runtime_snapshot(**kwargs)
    return json.loads((tmp_path / "runtime_snapshot.json").read_text(encoding="utf-8"))


def test_a_ctx_fallback_reports_the_true_original_request(tmp_path, monkeypatch):
    """The exact live scenario: operator asked ctx=12384, smart-fit landed on 4096."""
    snap = _write(
        tmp_path, monkeypatch,
        model_path="/models/Qwen3.6-35B-A3B-Q4_K_M.gguf",
        n_ctx=4096, n_threads=10, n_gpu_layers=11,
        n_batch_attr=128,
        requested_n_gpu_layers=10,
        requested_n_ctx=12384,
        requested_n_batch=128,
    )
    assert snap["requested"]["n_ctx"] == 12384, (
        "requested.n_ctx must preserve what the operator actually typed, "
        "not the smart-fit fallback that ended up loading"
    )
    assert snap["effective"]["n_ctx"] == 4096
    assert snap["requested"]["n_gpu_layers"] == 10
    assert snap["effective"]["n_gpu_layers"] == 11


def test_no_fallback_keeps_requested_and_effective_identical(tmp_path, monkeypatch):
    snap = _write(
        tmp_path, monkeypatch,
        model_path="/models/small.gguf",
        n_ctx=8192, n_threads=8, n_gpu_layers=99,
        n_batch_attr=512,
        requested_n_gpu_layers=99,
        requested_n_ctx=8192,
        requested_n_batch=512,
    )
    assert snap["requested"] == snap["effective"]


def test_omitting_requested_ctx_batch_falls_back_to_effective(tmp_path, monkeypatch):
    """Backward compatibility: a caller with no fallback story to tell (e.g. a
    plain re-publish) still gets a self-consistent snapshot, not a crash."""
    snap = _write(
        tmp_path, monkeypatch,
        model_path="/models/small.gguf",
        n_ctx=8192, n_threads=8, n_gpu_layers=99,
        n_batch_attr=512,
    )
    assert snap["requested"]["n_ctx"] == 8192
    assert snap["requested"]["n_batch"] == 512
