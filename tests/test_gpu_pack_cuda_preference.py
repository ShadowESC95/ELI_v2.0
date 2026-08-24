"""An NVIDIA machine must get -- and be told it got -- the CUDA pack.

Two regressions this guards, both seen on a live 2.3.22 install:

  * The installer downloaded cuda-llama_cpp_python-0.3.35 (797MB, libggml-cuda.so
    in the pack) and then wrote {"backend": "vulkan"} into .gpu_pack.json,
    because the CI-pack branch hardcoded the label. The installed backend was
    unreadable from disk.
  * That same branch required _vulkan_loader_present() before it would accept
    ANY CI-built pack, so an NVIDIA box with no Vulkan loader was refused a
    CUDA pack it could run perfectly well.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging" / "pyinstaller"))
import eli_gpu_pack  # noqa: E402


def test_cuda_asset_is_labelled_cuda():
    url = ("https://github.com/x/y/releases/download/gpu-packs/"
           "cuda-llama_cpp_python-0.3.35-py3-none-linux_x86_64.whl")
    assert eli_gpu_pack.pack_backend_from_url(url) == "cuda"


def test_vulkan_asset_is_labelled_vulkan():
    url = ("https://github.com/x/y/releases/download/gpu-packs/"
           "vulkan-llama_cpp_python-0.3.35-py3-none-linux_x86_64.whl")
    assert eli_gpu_pack.pack_backend_from_url(url) == "vulkan"


def _install_source() -> str:
    src = Path(eli_gpu_pack.__file__).read_text(encoding="utf-8")
    return src[src.index("def install("):]


def test_ci_pack_label_is_derived_not_hardcoded():
    body = Path(eli_gpu_pack.__file__).read_text(encoding="utf-8")
    assert 'backend, version, url = "vulkan", vk[0], vk[1]' not in body, (
        "the CI-pack branch hardcodes the vulkan label again; a CUDA pack "
        "would be recorded as vulkan in .gpu_pack.json")


def test_cuda_pick_does_not_require_a_vulkan_loader():
    body = Path(eli_gpu_pack.__file__).read_text(encoding="utf-8")
    assert "and _vulkan_loader_present():" not in body, (
        "the CI-pack branch gates unconditionally on the Vulkan loader again; "
        "an NVIDIA machine without libvulkan.so.1 would be denied a CUDA pack")
