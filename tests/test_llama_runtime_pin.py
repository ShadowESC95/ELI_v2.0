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
    assert any(f.endswith("/packaging/llama_cpp_constraints.txt") for f in wf["env"]["PIP_CONSTRAINT"].split())


def test_release_builds_keep_to_the_lock_and_every_job_writes_it_before_pip():
    """2.5.11's bundle took the newest PyAV, which refuses an argument faster-whisper 1.2.1 passes:
    every transcription in the packaged app failed. The build now installs under the lock."""
    wf = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    files = wf["env"]["PIP_CONSTRAINT"].split()
    # absolute: one step builds from a clean export of the committed tree, where this file is not
    assert "${{github.workspace}}/.build-constraints/lock.txt" in files
    for name, job in wf["jobs"].items():
        runs = [str(step.get("run") or "") for step in job.get("steps", [])]
        uses_pip = [i for i, r in enumerate(runs) if "pip " in r or "build_packages.sh" in r]
        if not uses_pip:
            continue
        writes = [i for i, r in enumerate(runs) if "lock_constraints.py .build-constraints/lock.txt" in r]
        assert writes and writes[0] < uses_pip[0], f"{name} runs pip before the lock constraints are written"


def test_the_lock_constraints_leave_out_only_what_the_build_tools_do_not_allow(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("lock_constraints", ROOT / "packaging" / "lock_constraints.py")
    lc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lc)
    lock = tmp_path / "lock.txt"
    lock.write_text('av==17.0.1\nsetuptools==81.0.0\nPillow==11.0.0\ncomtypes==1.4.17 ; sys_platform == "win32"\n')
    build = tmp_path / "build.txt"
    build.write_text("# tools\npyinstaller>=6.13,<7\nsetuptools>=70,<81\nPillow>=10.0\n")
    assert lc.constraints(lock, build) == ["av==17.0.1", "Pillow==11.0.0", 'comtypes==1.4.17 ; sys_platform == "win32"']
    real = lc.constraints(ROOT / "requirements.lock.txt", ROOT / "requirements-build.txt")
    assert any(x.startswith("av==") for x in real) and not any(x.startswith("setuptools==") for x in real)


def test_gpu_packs_are_built_at_the_pinned_version():
    """The packs and the bundles come from one source, whose version is the pin."""
    text = (ROOT / ".github/workflows/gpu-packs.yml").read_text()
    assert text.count('llama_src="$(python packaging/llama_source.py)"') == 2
    assert text.count('pip wheel "$llama_src"') == 2
    assert "llama-cpp-python==" not in text
    assert text.count("actions/checkout") == 2


@pytest.mark.parametrize("path, installs", [(".github/workflows/release.yml", 2), ("packaging/ci_linux_deps.sh", 1),
                                            (".github/workflows/cross-platform-smoke.yml", 1)])
def test_everything_that_installs_the_runtime_takes_it_from_that_source(path, installs):
    text = (ROOT / path).read_text()
    assert text.count('llama_src="$(python packaging/llama_source.py)"') == installs
    assert text.count('pip install "$llama_src"') == installs
    assert "pip install llama-cpp-python" not in text


@pytest.mark.parametrize("path", [".github/workflows/release.yml", "packaging/ci_linux_deps.sh"])
def test_the_runtime_goes_in_before_the_extra_that_asks_for_it(path):
    """Held to a version PyPI does not have, the llm extra only finds it already installed."""
    lines = (ROOT / path).read_text().splitlines()
    source = [i for i, line in enumerate(lines) if "packaging/llama_source.py" in line]
    extras = [i for i, line in enumerate(lines) if "REQUIRED_EXTRAS | tr" in line]
    assert len(source) == len(extras) and all(0 < e - s <= 2 for s, e in zip(source, extras))


def _source_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("llama_source", ROOT / "packaging" / "llama_source.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_pin_is_not_a_version_upstream_publishes_and_every_parser_reads_it():
    """Under upstream's number an installed pack of the old build would look current and be mixed in."""
    sys.path.insert(0, str(ROOT / "packaging" / "pyinstaller"))
    import eli_gpu_pack as gp
    pin = _source_module().pinned_version()
    assert pin == _pinned() and pin != "0.3.36"
    assert ".".join(str(n) for n in gp._ver_tuple(pin)) == pin
    assert re.fullmatch(r"\d+(?:\.\d+)+", pin)  # the wheel patterns in eli_gpu_pack stop at anything else


def test_a_binding_change_that_no_longer_applies_stops_the_build(tmp_path):
    source = _source_module()
    (tmp_path / "llama_cpp").mkdir()
    for name, old, _new in source.BINDING_CHANGES:
        path = tmp_path / name
        path.write_text((path.read_text() if path.exists() else "") + old)
    source.apply_binding_changes(tmp_path)
    text = (tmp_path / "llama_cpp" / "llama_cpp.py").read_text()
    assert '("moe_cache_size", ctypes.c_size_t)' in text and "LLAMA_STATE_SEQ_VERSION = 4" in text
    with pytest.raises(SystemExit):
        source.apply_binding_changes(tmp_path)


@pytest.mark.parametrize("filters", [True, False])
def test_the_source_unpacks_with_or_without_extraction_filters(tmp_path, monkeypatch, filters):
    """The last 3.10 with installers (macOS, Windows) has no filter=, and the source was never unpacked there."""
    import io
    import tarfile
    source = _source_module()
    if not filters:
        monkeypatch.delattr(tarfile, "data_filter")

    def archive(name, *entries):
        path = tmp_path / name
        with tarfile.open(path, "w:gz") as tar:
            for entry, data in entries:
                tar.addfile(entry, io.BytesIO(data) if data else None)
        return path

    def entry(name, data=b"", link=""):
        info = tarfile.TarInfo(name)
        info.size = len(data)
        if link:
            info.type, info.linkname = tarfile.SYMTYPE, link
        return info, data

    source._unpack(archive("good.tar.gz", entry("top/setup.py", b"x"), entry("top/latest", link="setup.py")),
                   tmp_path / "out")
    assert (tmp_path / "out" / "top" / "setup.py").read_bytes() == b"x"
    for bad in (entry("../escaped", b"z"), entry("top/away", link="../../escaped")):
        with pytest.raises((SystemExit, tarfile.TarError)):
            source._unpack(archive("bad.tar.gz", bad), tmp_path / "bad")
    assert not (tmp_path / "escaped").exists()


def test_the_version_is_stamped_on_the_source(tmp_path):
    source = _source_module()
    (tmp_path / "llama_cpp").mkdir()
    (tmp_path / "llama_cpp" / "__init__.py").write_text('__version__ = "0.3.36"\n')
    source.stamp_version(tmp_path, "9.9.9.1")
    assert '__version__ = "9.9.9.1"' in (tmp_path / "llama_cpp" / "__init__.py").read_text()


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
    # not through ELI_PROJECT_ROOT: any thread's load_settings() removes a path outside the install
    monkeypatch.setattr(eli_gpu_pack, "_eli_root", lambda: tmp_path / "root")
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


def test_a_pack_is_not_loaded_over_a_different_build_already_running(gp, tmp_path, monkeypatch):
    dest = _pack(tmp_path, "0.3.36")
    running = types.ModuleType("llama_cpp")
    running.__file__ = str(tmp_path / "elsewhere" / "llama_cpp" / "__init__.py")
    running.__version__ = "0.3.35"
    monkeypatch.setitem(sys.modules, "llama_cpp", running)
    monkeypatch.setattr(gp, "preload_native_libs",
                        lambda *_: pytest.fail("loaded a second build into the process"))
    before = list(sys.path)
    assert gp.activate_gpu_pack_runtime(dest, verify=True) is False
    assert sys.path == before and sys.modules["llama_cpp"] is running


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


def test_a_pack_from_an_earlier_version_is_named_as_such(gp, tmp_path):
    dest = _pack(tmp_path, "0.3.35")
    assert gp.outdated_pack(dest) == "0.3.35"
    (dest / "llama_cpp" / "__init__.py").write_text('__version__ = "0.3.36"\n')
    assert gp.outdated_pack(dest) is None


_OFFER = """
import importlib.util, json, sys
s = importlib.util.spec_from_file_location("eli_entry", sys.argv[1])
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
sys.frozen, sys._MEIPASS = True, sys.argv[2]
gp, calls = m._gpu_pack_module(), []
def install(argv, progress=None):
    progress("Downloading pack.whl: 1 / 2 MB", 50)
    calls.append(argv)
    return 1
def dialog(*, title, label, work_fn):
    state = {"pct": 0}
    rc = work_fn(state)
    calls.append([label, state["label"], state["pct"]])
    return rc
gp.install, m._run_progress_dialog = install, dialog
m._message_box_ask = lambda **k: calls.append("asked")
m._message_box_warning = lambda *a: None
m._first_run_gpu_offer()
print(json.dumps(calls))
"""


@pytest.mark.parametrize("backend, argv", [("cuda", ["--force"]), ("vulkan", ["--vulkan", "--force"])])
def test_an_update_brings_the_pack_up_to_date_without_asking_again(gp, tmp_path, backend, argv):
    """2.5.18 asked a 2.5.17 GPU user the first-install question again, sized from a guess."""
    import os
    import subprocess
    if sys.platform == "darwin":
        pytest.skip("macOS builds carry Metal, no pack")
    dest = _pack(tmp_path, "0.3.35")
    (dest / ".gpu_pack.json").write_text(json.dumps({"version": "0.3.35", "backend": backend}))
    (dest.parent / ".gpu_choice").write_text("gpu-installed")
    entry = ROOT / "packaging" / "pyinstaller" / "eli_entry.py"
    out = subprocess.run([sys.executable, "-c", _OFFER, str(entry), sys._MEIPASS],
                         env={**os.environ, "ELI_PROJECT_ROOT": str(tmp_path / "root")},
                         capture_output=True, text=True, timeout=120, cwd=ROOT, check=True)
    calls = json.loads(out.stdout.strip().splitlines()[-1])
    assert "asked" not in calls
    assert calls[0] == argv
    label, shown, pct = calls[1]
    assert "0.3.35 → 0.3.36" in label and shown == "Downloading pack.whl: 1 / 2 MB" and pct == 50
