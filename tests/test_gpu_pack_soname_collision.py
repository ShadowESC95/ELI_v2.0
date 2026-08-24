"""The GPU pack must preload its OWN libggml.so, or the frozen app captures it.

Regression for: ELI 2.3.21/2.3.22 reported "llama.cpp GPU offload support:
False" on a working NVIDIA GPU. The AppImage keeps a CPU-only libggml.so.0 at
the top of _internal, which is on LD_LIBRARY_PATH. The pack's libllama.so
records "NEEDED libggml.so.0"; because preload_native_libs() loaded only the
-base/-cpu/-vulkan/-cuda backends and never libggml.so itself, the linker
satisfied that NEEDED from the bundle's CPU-only copy. The pack's GPU backend
then never registered and the app silently fell back to CPU.
"""
import ctypes
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging" / "pyinstaller"))
import eli_gpu_pack  # noqa: E402


def _fake_pack(tmp_path):
    lib = tmp_path / "llama_cpp" / "lib"
    lib.mkdir(parents=True)
    for n in ("libggml-base.so", "libggml-cpu.so", "libggml-vulkan.so",
              "libggml.so", "libllama.so", "libmtmd.so"):
        (lib / n).write_bytes(b"\x7fELF")
    return tmp_path


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SONAME semantics")
def test_pack_preloads_its_own_ggml_dispatcher(tmp_path, monkeypatch):
    loaded = []

    def _fake_cdll(path, *a, **k):
        loaded.append(str(path))
        return types.SimpleNamespace()

    monkeypatch.setattr(ctypes, "CDLL", _fake_cdll)
    eli_gpu_pack.preload_native_libs(_fake_pack(tmp_path))

    names = [Path(p).name for p in loaded]
    assert "libggml.so" in names, (
        "libggml.so was never preloaded; the frozen app's CPU-only "
        "libggml.so.0 on LD_LIBRARY_PATH will capture the pack's NEEDED "
        "and the GPU backend will not register. Loaded: %r" % names)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SONAME semantics")
def test_ggml_base_is_loaded_before_the_dispatcher(tmp_path, monkeypatch):
    loaded = []
    monkeypatch.setattr(ctypes, "CDLL",
                        lambda p, *a, **k: (loaded.append(str(p)),
                                            types.SimpleNamespace())[1])
    eli_gpu_pack.preload_native_libs(_fake_pack(tmp_path))
    names = [Path(p).name for p in loaded]
    assert names.index("libggml-base.so") < names.index("libggml.so"), (
        "dependency order violated: libggml.so must load after libggml-base.so")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SONAME semantics")
def test_llama_and_mtmd_are_not_preloaded(tmp_path, monkeypatch):
    """Preloading libllama/libmtmd too caused a double-free at exit.

    llama_cpp loads libllama.so itself by absolute path. Adding an RTLD_GLOBAL
    preload of the same file made offload report True and then killed the
    process on the way out with "double free or corruption (!prev)". Only the
    ggml libraries -- which nothing else loads by absolute path -- belong here.
    """
    loaded = []
    monkeypatch.setattr(ctypes, "CDLL",
                        lambda p, *a, **k: (loaded.append(str(p)),
                                            types.SimpleNamespace())[1])
    eli_gpu_pack.preload_native_libs(_fake_pack(tmp_path))
    names = [Path(p).name for p in loaded]
    for n in ("libllama.so", "libmtmd.so"):
        assert n not in names, (
            f"{n} must not be preloaded: llama_cpp loads it by absolute path "
            f"and the duplicate RTLD_GLOBAL load double-frees at exit. "
            f"Loaded: {names!r}")
