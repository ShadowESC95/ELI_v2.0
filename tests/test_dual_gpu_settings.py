"""Dual/multi-GPU settings → env publish + tensor_split resolution. Offline, no GPU needed."""
import json
import os

from eli.core import runtime_settings as rs
from eli.core.startup_hardware_optimizer import recommend_tensor_split, GPUInfo


def _clear():
    for k in ("ELI_GGUF_TENSOR_SPLIT", "ELI_GGUF_MAIN_GPU", "ELI_GGUF_SPLIT_MODE"):
        os.environ.pop(k, None)


def test_single_gpu_publishes_no_split():
    _clear()
    rs.apply_env({"tensor_split": "", "main_gpu": 0, "split_mode": ""})
    assert os.environ.get("ELI_GGUF_TENSOR_SPLIT") is None


def test_explicit_setting_published():
    _clear()
    rs.apply_env({"tensor_split": "0.5,0.5", "main_gpu": 0, "split_mode": "layer"})
    assert os.environ["ELI_GGUF_TENSOR_SPLIT"] == "0.5,0.5"
    assert os.environ["ELI_GGUF_SPLIT_MODE"] == "layer"
    _clear()


def test_profile_file_resolves_enabled_split(tmp_path):
    prof = {"profiles": [
        {"name": "off", "enabled": False, "tensor_split": None},
        {"name": "dual", "enabled": True, "main_gpu": 0,
         "tensor_split": [0.5, 0.5], "split_mode": "layer"},
    ]}
    f = tmp_path / "gpu_profiles.json"
    f.write_text(json.dumps(prof))
    ts, mg, sm = rs._resolve_gpu_split(
        {"tensor_split": "", "main_gpu": 0, "split_mode": "", "gpu_profiles_file": str(f)})
    assert ts == "0.5,0.5" and mg == 0 and sm == "layer"


def test_recommend_tensor_split_is_vram_proportional():
    assert recommend_tensor_split([GPUInfo(0, "g", "nvidia", 8192, 8000)]) == ""   # 1 GPU → none
    out = recommend_tensor_split([GPUInfo(0, "a", "nvidia", 8192, 8000),
                                  GPUInfo(1, "b", "nvidia", 24576, 24000)])
    assert out == "0.25,0.75"   # proportional to total VRAM


def test_shipped_profiles_file_is_valid_and_disabled():
    """The shipped config/gpu_profiles.json must be valid and all-disabled (single-GPU no-op)."""
    from eli.core.runtime_settings import _eli_runtime_physical_project_root
    p = _eli_runtime_physical_project_root() / "config" / "gpu_profiles.json"
    if not p.is_file():
        return  # not present in this checkout; template covers it
    data = json.loads(p.read_text())
    assert all(not prof.get("enabled") for prof in data.get("profiles", []))
