"""Bundled GPU pack discovery for offline-first frozen/portable installs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging" / "pyinstaller"))
import eli_gpu_pack  # noqa: E402


def test_pick_bundled_wheel_prefers_cuda(tmp_path, monkeypatch):
    d = tmp_path / "gpu-packs"
    d.mkdir()
    vulkan = d / "vulkan-llama_cpp_python-0.3.35-py3-none-linux_x86_64.whl"
    cuda = d / "cuda-llama_cpp_python-0.3.35-py3-none-linux_x86_64.whl"
    vulkan.write_bytes(b"x")
    cuda.write_bytes(b"x")
    monkeypatch.setattr(eli_gpu_pack, "_bundled_gpu_dir", lambda: d)
    pick = eli_gpu_pack._pick_bundled_wheel(prefer_cuda=True)
    assert pick is not None
    assert pick[0] == "cuda"
    assert pick[2] == cuda


def test_pick_bundled_wheel_vulkan_when_no_cuda(tmp_path, monkeypatch):
    d = tmp_path / "gpu-packs"
    d.mkdir()
    vulkan = d / "vulkan-llama_cpp_python-0.3.35-py3-none-linux_x86_64.whl"
    vulkan.write_bytes(b"x")
    monkeypatch.setattr(eli_gpu_pack, "_bundled_gpu_dir", lambda: d)
    pick = eli_gpu_pack._pick_bundled_wheel(prefer_cuda=True)
    assert pick is not None
    assert pick[0] == "vulkan"
