"""One llama.cpp build per process, on every OS.

v2.5.0 crashed on launch wherever a GPU pack was installed:
  libllama.so: undefined symbol: ggml_rope_set_offset
The release resolved "llama-cpp-python>=0.2" to the newest upstream (0.3.36,
published 2026-10-01) while the GPU packs were built at 0.3.35. A pack and the
bundled runtime share native library names, so once one libggml is loaded it
serves both. Then the failed activation deleted the pack's verified marker.

Fixed at both ends: releases pin the bundled version to the packs', and at runtime
a pack is only activated, accepted as installed, or downloaded when it is the
bundled runtime's exact version.
"""
import json
import re
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONSTRAINTS = ROOT / "packaging" / "llama_cpp_constraints.txt"


def _pinned() -> str:
    pins = re.findall(r"^llama-cpp-python==(\S+)\s*$", CONSTRAINTS.read_text(), re.M)
    assert len(pins) == 1, pins
    return pins[0]


# ── the pin, everywhere it has to agree ──────────────────────────────────────

def test_release_builds_install_the_pinned_runtime():
    wf = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    assert wf["env"]["PIP_CONSTRAINT"] == "packaging/llama_cpp_constraints.txt"


def test_gpu_packs_are_built_at_the_pinned_version():
    text = (ROOT / ".github/workflows/gpu-packs.yml").read_text()
    wf = yaml.safe_load(text)
    on = wf.get("on") or wf.get(True)
    assert on["workflow_dispatch"]["inputs"]["llama_version"]["default"] == _pinned()
    assert f"|| '{_pinned()}'" in wf["env"]["LLAMA_VERSION"]


def test_offline_fallback_assets_include_the_pinned_version():
    sys.path.insert(0, str(ROOT / "packaging" / "pyinstaller"))
    import eli_gpu_pack as gp
    for kind in ("cuda", "vulkan"):
        for plat in ("linux_x86_64", "win_amd64"):
            assert f"{kind}-llama_cpp_python-{_pinned()}-py3-none-{plat}.whl" in gp._GPU_PACK_FALLBACK_ASSETS


# ── the runtime guard ────────────────────────────────────────────────────────

@pytest.fixture()
def gp(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "packaging" / "pyinstaller"))
    import eli_gpu_pack
    meipass = tmp_path / "bundle"
    (meipass / "llama_cpp").mkdir(parents=True)
    (meipass / "llama_cpp" / "__init__.py").write_text('__version__ = "0.3.36"\n')
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setenv("ELI_PROJECT_ROOT", str(tmp_path / "root"))
    return eli_gpu_pack


def _pack(root: Path, version: str, marker: bool = True) -> Path:
    dest = root / "root" / "runtime" / "gpu"
    (dest / "llama_cpp" / "lib").mkdir(parents=True)
    (dest / "llama_cpp" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (dest / "llama_cpp" / "lib" / "libggml-cuda.so").write_bytes(b"")
    (dest / ".gpu_pack.json").write_text(json.dumps({"version": version, "backend": "cuda"}))
    if marker:
        (dest / ".gpu_pack_ok").write_text("verified")
    return dest


def test_a_mismatched_pack_is_never_loaded_into_the_process(gp, tmp_path, monkeypatch):
    dest = _pack(tmp_path, "0.3.35")
    monkeypatch.setattr(gp, "preload_native_libs",
                        lambda *_: pytest.fail("loaded a mismatched pack's native libraries"))
    before = list(sys.path)
    assert gp.activate_gpu_pack_runtime(dest, verify=True) is False
    assert sys.path == before
    assert (dest / ".gpu_pack_ok").is_file()  # verified once; left alone


def test_a_mismatched_pack_does_not_count_as_installed(gp, tmp_path):
    dest = _pack(tmp_path, "0.3.35")
    assert gp.pack_matches_runtime(dest) is False
    assert gp.gpu_pack_looks_installed(dest) is False
    assert gp.gpu_pack_operational(dest) is False


def test_a_matching_pack_counts_as_installed(gp, tmp_path):
    dest = _pack(tmp_path, "0.3.36")
    assert gp.pack_matches_runtime(dest) is True
    assert gp.gpu_pack_looks_installed(dest) is True


def test_only_the_runtime_version_is_downloaded(gp, monkeypatch):
    assets = {"assets": [
        {"name": "cuda-llama_cpp_python-0.3.35-py3-none-linux_x86_64.whl", "browser_download_url": "u35"},
        {"name": "cuda-llama_cpp_python-0.3.36-py3-none-linux_x86_64.whl", "browser_download_url": "u36"},
        {"name": "cuda-llama_cpp_python-0.3.37-py3-none-linux_x86_64.whl", "browser_download_url": "u37"},
    ]}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(assets).encode()

    monkeypatch.setattr(gp, "_platform_tag", lambda: "linux_x86_64")
    with patch.object(gp.urllib.request, "urlopen", lambda *a, **k: _Resp()), \
            patch.object(gp.json, "load", lambda r: assets):
        assert gp._pick_vulkan_wheel(prefer_cuda=True) == ("0.3.36", "u36")  # not the newest, 0.3.37


def test_a_lost_marker_is_restored_by_reverifying_not_by_downloading(gp, tmp_path, monkeypatch):
    dest = _pack(tmp_path, "0.3.36", marker=False)
    monkeypatch.setattr(gp, "_verify", lambda *a, **k: (True, "ok"))
    assert gp.gpu_pack_operational(dest) is True
    assert (dest / ".gpu_pack_ok").is_file()


def test_activation_is_idempotent(gp, tmp_path, monkeypatch):
    dest = _pack(tmp_path, "0.3.36")
    fake = types.ModuleType("llama_cpp")
    fake.__file__ = str(dest.resolve() / "llama_cpp" / "__init__.py")
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)
    monkeypatch.setattr(gp, "preload_native_libs",
                        lambda *_: pytest.fail("re-activated an already active pack"))
    assert gp.activate_gpu_pack_runtime(dest, verify=True) is True


def test_a_failed_activation_no_longer_deletes_the_marker():
    src = (ROOT / "packaging" / "pyinstaller" / "eli_entry.py").read_text()
    i = src.index("def _first_run_gpu_offer(")
    body = src[i:src.index("\ndef ", i + 10)]
    j = body.index("if not _gp.activate_gpu_pack_runtime(dest, verify=True):")
    assert ".unlink(" not in body[j:j + 400]
