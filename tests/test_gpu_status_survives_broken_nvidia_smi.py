"""Reported: ELI couldn't answer "what is my GPU?" or "what are your settings"
-- not because it lied, but because a single live nvidia-smi failure (NVML
"Driver/library version mismatch") made _gpu_status_report() bail out with
just the raw error text, before it ever reached the runtime_snapshot section
(context/gpu_layers/batch/threads) that has nothing to do with nvidia-smi at
all. So a question about LOADED SETTINGS got "not specified in the evidence"
for a reason entirely unrelated to the question asked.

_gpu_status_report() now delegates all vendor dispatch (NVIDIA live query,
AMD rocm-smi, cross-vendor identity fallback) to
hardware_profile.get_live_gpu_telemetry() -- that cascade is covered
thoroughly in test_get_live_gpu_telemetry.py. This file covers
_gpu_status_report()'s OWN job: formatting whatever telemetry it's handed,
and never losing the runtime_snapshot section regardless of what the GPU
probe found.
"""
import json

import eli.execution.executor_enhanced as ex

SNAPSHOT = {
    "provider": "gguf", "model_name": "Qwen_Qwen3-8B-Q4_K_M.gguf",
    "n_ctx": 12000, "n_gpu_layers": 32, "n_threads": 10, "n_batch": 128,
}


def _telem(**kw):
    base = {
        "ok": False, "name": "", "vendor": "", "estimated": False,
        "total_mb": None, "free_mb": None, "used_mb": None,
        "util_pct": None, "temp_c": None, "power_w": None, "power_limit_w": None,
        "driver": None, "live_probe_failed": False,
    }
    base.update(kw)
    return base


def _setup(monkeypatch, tmp_path, *, snapshot=None, telemetry=None):
    if snapshot is not None:
        (tmp_path / "runtime_snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")

    class _Paths:
        artifacts_dir = tmp_path
    monkeypatch.setattr(ex, "get_paths", lambda: _Paths())
    if telemetry is not None:
        monkeypatch.setattr(
            "eli.core.hardware_profile.get_live_gpu_telemetry", lambda: telemetry,
        )


def test_loaded_settings_still_reported_when_gpu_probe_failed(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, snapshot=SNAPSHOT, telemetry=_telem())
    rep = ex._gpu_status_report()
    assert "context: 12000" in rep["content"]
    assert "GPU-layer parameter: 32" in rep["content"]
    assert "batch: 128" in rep["content"]
    assert "CPU threads: 10" in rep["content"]


def test_ok_is_true_when_there_is_genuinely_grounded_content(monkeypatch, tmp_path):
    """A live-probe failure is not the same as having nothing to say -- ok
    must reflect whether the report is USABLE, not whether the probe ran."""
    _setup(monkeypatch, tmp_path, snapshot=SNAPSHOT, telemetry=_telem())
    rep = ex._gpu_status_report()
    assert rep["ok"] is True


def test_gpu_name_and_estimate_note_are_shown(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, snapshot=SNAPSHOT, telemetry=_telem(
        ok=True, name="NVIDIA GeForce RTX 2060 SUPER", vendor="nvidia",
        total_mb=8192, live_probe_failed=True, estimated=True,
    ))
    rep = ex._gpu_status_report()
    assert "NVIDIA GeForce RTX 2060 SUPER" in rep["content"]
    assert "8192" in rep["content"]
    assert "estimated" in rep["content"].lower()


def test_no_snapshot_and_no_gpu_is_still_honest_not_silent(monkeypatch, tmp_path):
    """Genuinely nothing known: ok=False is correct here, but content must
    still say so plainly rather than an empty/unhelpful string."""
    _setup(monkeypatch, tmp_path, snapshot=None, telemetry=_telem())
    rep = ex._gpu_status_report()
    assert rep["ok"] is False
    assert "No GPU detected" in rep["content"]


def test_full_live_telemetry_is_all_rendered(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, snapshot=SNAPSHOT, telemetry=_telem(
        ok=True, name="NVIDIA GeForce RTX 2060 SUPER", vendor="nvidia",
        total_mb=8192, used_mb=1200, free_mb=6963, util_pct=12, temp_c=44,
        power_w=24.5, power_limit_w=215.0, driver="595.91",
    ))
    rep = ex._gpu_status_report()
    c = rep["content"]
    assert "1200 MiB used" in c
    assert "6963 MiB free" in c
    assert "12%" in c
    assert "44 C" in c
    assert "24.50 W" in c
    assert "595.91" in c


def test_intel_igpu_content_never_mentions_nvidia(monkeypatch, tmp_path):
    """Vendor dispatch itself lives in get_live_gpu_telemetry() -- this just
    checks the rendered text doesn't leak nvidia-specific wording for a
    non-NVIDIA vendor's telemetry."""
    _setup(monkeypatch, tmp_path, snapshot=SNAPSHOT, telemetry=_telem(
        ok=True, name="Intel Iris Xe Graphics", vendor="intel", total_mb=4096,
    ))
    rep = ex._gpu_status_report()
    assert "Intel Iris Xe Graphics" in rep["content"]
    assert "nvidia" not in rep["content"].lower()
    assert "context: 12000" in rep["content"]


def test_amd_used_vram_is_rendered(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, snapshot=SNAPSHOT, telemetry=_telem(
        ok=True, name="AMD Radeon RX 7900 XTX", vendor="amd",
        total_mb=24576, used_mb=4096, free_mb=20480,
    ))
    rep = ex._gpu_status_report()
    assert rep["ok"] is True
    assert "AMD Radeon RX 7900 XTX" in rep["content"]
    assert "4096 MiB used" in rep["content"]
    assert "context: 12000" in rep["content"]
