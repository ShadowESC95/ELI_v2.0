"""GPU pack backend selection must match the machine — and be complete.

Regressions this guards (seen on live installs):

  * NVIDIA CI-pack path downloaded cuda-llama_cpp_python but wrote
    {"backend": "vulkan"} into .gpu_pack.json.
  * That same branch required _vulkan_loader_present() for ANY CI pack, so an
    NVIDIA box without Vulkan was refused a CUDA pack it could run.
  * Iris Xe / ``--vulkan`` / AMD path used the same picker, which preferred
    cuda- assets, then hardcoded backend="vulkan" and skipped cudart vendoring.
    Result: 2.7 GB pack with libggml-cuda.so and no libcudart.so.12.
  * ``"cuda".startswith("cu")`` was treated as a cuNNN pin, breaking vendoring.
"""
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


def test_normalize_cuda_idx_never_treats_cuda_as_cuNNN():
    assert eli_gpu_pack._normalize_cuda_idx("cu124") == "cu124"
    assert eli_gpu_pack._normalize_cuda_idx("cu126") == "cu126"
    # Bare "cuda" must map to the CI toolkit line (12.6), not cu124 — cu124
    # against a 12.6-built libggml-cuda.so failed verify on live NVIDIA boxes.
    assert eli_gpu_pack._normalize_cuda_idx("cuda") == "cu126"
    assert eli_gpu_pack._normalize_cuda_idx("vulkan") == "cu126"
    assert eli_gpu_pack._normalize_cuda_idx("") == "cu126"


def test_ci_pack_label_is_derived_not_hardcoded():
    body = Path(eli_gpu_pack.__file__).read_text(encoding="utf-8")
    assert 'backend, version, url = "vulkan", vk[0], vk[1]' not in body, (
        "the CI-pack branch hardcodes the vulkan label again; a CUDA pack "
        "would be recorded as vulkan in .gpu_pack.json")
    assert 'backend, (version, url) = "vulkan", found' not in body, (
        "the AMD/Intel/--vulkan branch hardcodes vulkan again after pick")


def test_cuda_pick_does_not_require_a_vulkan_loader():
    body = Path(eli_gpu_pack.__file__).read_text(encoding="utf-8")
    assert "and _vulkan_loader_present():" not in body, (
        "the CI-pack branch gates unconditionally on the Vulkan loader again; "
        "an NVIDIA machine without libvulkan.so.1 would be denied a CUDA pack")


def test_vulkan_only_picker_ignores_cuda_assets(monkeypatch):
    import io
    import json
    from contextlib import nullcontext

    assets = [
        {
            "name": "cuda-llama_cpp_python-0.3.35-py3-none-linux_x86_64.whl",
            "browser_download_url": "https://example/cuda-0.3.35.whl",
        },
        {
            "name": "vulkan-llama_cpp_python-0.3.35-py3-none-linux_x86_64.whl",
            "browser_download_url": "https://example/vulkan-0.3.35.whl",
        },
    ]

    monkeypatch.setattr(
        eli_gpu_pack.urllib.request,
        "urlopen",
        lambda *a, **k: nullcontext(io.BytesIO(json.dumps({"assets": assets}).encode())),
    )
    monkeypatch.setattr(eli_gpu_pack, "_platform_tag", lambda: "linux_x86_64")

    class _VI:
        major = 3
        minor = 12

    monkeypatch.setattr(eli_gpu_pack.sys, "version_info", _VI())

    only_vk = eli_gpu_pack._pick_vulkan_wheel(prefer_cuda=False)
    assert only_vk is not None
    assert only_vk[1].endswith("vulkan-0.3.35.whl")

    prefer_cu = eli_gpu_pack._pick_vulkan_wheel(prefer_cuda=True)
    assert prefer_cu is not None
    assert prefer_cu[1].endswith("cuda-0.3.35.whl")


def test_assert_cuda_runtime_complete_fails_without_cudart(tmp_path):
    lib = tmp_path / "llama_cpp" / "lib"
    lib.mkdir(parents=True)
    (lib / "libggml-cuda.so").write_bytes(b"x")
    try:
        eli_gpu_pack._assert_cuda_runtime_complete(lib)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "libcudart" in str(exc)


def test_assert_cuda_runtime_complete_ok_with_cudart_cublas(tmp_path):
    lib = tmp_path / "llama_cpp" / "lib"
    lib.mkdir(parents=True)
    (lib / "libggml-cuda.so").write_bytes(b"x")
    (lib / "libcudart.so.12").write_bytes(b"x")
    (lib / "libcublas.so.12").write_bytes(b"x")
    eli_gpu_pack._assert_cuda_runtime_complete(lib)


def test_dedupe_removes_duplicate_top_level_natives(tmp_path):
    staging = tmp_path / "staging"
    primary = staging / "llama_cpp" / "lib"
    dup = staging / "lib"
    primary.mkdir(parents=True)
    dup.mkdir(parents=True)
    (primary / "libggml-cuda.so").write_bytes(b"prim")
    (dup / "libggml-cuda.so").write_bytes(b"dup")
    (dup / "keep_me.txt").write_text("docs")
    eli_gpu_pack._dedupe_wheel_native_trees(staging)
    assert (primary / "libggml-cuda.so").is_file()
    assert not (dup / "libggml-cuda.so").exists()
    assert (dup / "keep_me.txt").is_file()


def test_vulkan_picker_falls_back_when_api_fails(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("API rate limit")

    monkeypatch.setattr(eli_gpu_pack.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(eli_gpu_pack, "_platform_tag", lambda: "linux_x86_64")

    class _VI:
        major = 3
        minor = 12

    monkeypatch.setattr(eli_gpu_pack.sys, "version_info", _VI())

    picked = eli_gpu_pack._pick_vulkan_wheel(prefer_cuda=False)
    assert picked is not None
    assert picked[0] == "0.3.35"
    assert picked[1].endswith("vulkan-llama_cpp_python-0.3.35-py3-none-linux_x86_64.whl")
    assert "cuda-" not in picked[1]


def test_nvidia_smi_error_stdout_is_not_a_gpu():
    assert not eli_gpu_pack._nvidia_smi_stdout_usable(
        "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver"
    )
    assert eli_gpu_pack._nvidia_smi_stdout_usable("NVIDIA GeForce GTX 1660 Ti")
    assert eli_gpu_pack._nvidia_smi_stdout_usable("GPU 0: GeForce RTX 3060 (UUID: GPU-…)")


def test_gpu_pack_install_opens_netguard_allow_window():
    body = Path(eli_gpu_pack.__file__).read_text(encoding="utf-8")
    assert 'allow_network("gpu-pack install")' in body, (
        "GPU pack install must open a scoped NetGuard window; otherwise "
        "offline-by-default blocks abetlen.github.io / github.com / pypi.org"
    )


def test_nvidia_falls_back_to_ci_cuda_when_index_empty():
    body = Path(eli_gpu_pack.__file__).read_text(encoding="utf-8")
    assert "trying CI-built CUDA pack from the gpu-packs release" in body


def test_verify_trusts_cuda_device_enumeration_on_false_negative():
    body = Path(eli_gpu_pack.__file__).read_text(encoding="utf-8")
    assert "cuda devices enumerated" in body
    assert "LD_LIBRARY_PATH" in body
    assert 'ggml_cuda_init:\\s*found\\s+[1-9]' in body or "ggml_cuda_init:" in body
