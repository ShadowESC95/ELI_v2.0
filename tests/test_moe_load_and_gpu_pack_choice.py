"""Two bugs behind a 20-minute 2.4.98 launch (2026-10-03, RTX 2060 SUPER 8 GB,
32 GB RAM, Qwen3.6-35B-A3B Q4_K_M).

1. The load hung. The 0.3.35 GPU pack's llama.cpp put the 17.7 GB of expert
   tensors (kept in RAM by moe_offload) into pinned CUDA host memory, which
   stalled at 12 GB RSS while the machine swapped. With pinning off it
   repacked them instead (another 14.4 GB copy: 265 s, 1.6 tok/s). Reading them
   in place from the file mapping: 2 s warm / 75 s cold, ~18 tok/s.

2. The GPU pack was downloaded again on every launch. A "Use CPU only" answer
   from September stayed in runtime/.gpu_choice, switched the installed pack
   off at boot, the load screen said "not installed", and its Install button
   passed --force: ~1.2 GB again, three times in one day.
"""
import ctypes
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "packaging" / "pyinstaller"
STARTUP = ROOT / "eli" / "gui" / "panels" / "startup.py"


# ── 1. expert tensors are read in place ──────────────────────────────────────

class _NewParams(ctypes.Structure):
    _fields_ = [("n_gpu_layers", ctypes.c_int), ("use_extra_bufts", ctypes.c_bool),
                ("no_host", ctypes.c_bool)]


class _OldParams(ctypes.Structure):
    _fields_ = [("n_gpu_layers", ctypes.c_int)]


def test_experts_are_neither_pinned_nor_repacked(monkeypatch):
    from eli.core.moe_offload import apply_zero_copy
    monkeypatch.delenv("ELI_MOE_PINNED_EXPERTS", raising=False)
    p = _NewParams(n_gpu_layers=40, use_extra_bufts=True, no_host=False)
    apply_zero_copy(p)
    assert p.no_host is True
    assert p.use_extra_bufts is False
    assert p.n_gpu_layers == 40


def test_an_older_build_without_the_fields_is_left_alone(monkeypatch):
    from eli.core.moe_offload import apply_zero_copy
    monkeypatch.delenv("ELI_MOE_PINNED_EXPERTS", raising=False)
    p = apply_zero_copy(_OldParams(n_gpu_layers=40))
    assert not hasattr(p, "no_host") and not hasattr(p, "use_extra_bufts")


def test_big_ram_machines_can_keep_llamacpp_defaults(monkeypatch):
    from eli.core.moe_offload import apply_zero_copy
    monkeypatch.setenv("ELI_MOE_PINNED_EXPERTS", "1")
    p = apply_zero_copy(_NewParams(use_extra_bufts=True, no_host=False))
    assert p.no_host is False and p.use_extra_bufts is True


def test_every_loader_gets_it_through_the_one_patch():
    """GUI, engine and load probe all build through expert_offload_params()."""
    import inspect
    from eli.core import moe_offload
    src = inspect.getsource(moe_offload.expert_offload_params)
    assert "return apply_zero_copy(params)" in src


# ── 2. an installed pack is switched back on, not downloaded again ───────────

@pytest.fixture()
def gp(tmp_path, monkeypatch):
    sys.path.insert(0, str(PACK_DIR))
    import eli_gpu_pack
    monkeypatch.setenv("ELI_PROJECT_ROOT", str(tmp_path))
    return eli_gpu_pack


def _install_fake_pack(root: Path, choice: str = "") -> None:
    gpu = root / "runtime" / "gpu"
    (gpu / "llama_cpp" / "lib").mkdir(parents=True)
    (gpu / "llama_cpp" / "lib" / "libggml-cuda.so").write_bytes(b"")
    (gpu / ".gpu_pack_ok").write_text("verified")
    (gpu / ".gpu_pack.json").write_text(json.dumps({"version": "0.3.35", "backend": "cuda"}))
    if choice:
        (root / "runtime" / ".gpu_choice").write_text(choice)


def test_an_installed_pack_kept_off_by_an_old_cpu_choice_is_detected(gp, tmp_path):
    _install_fake_pack(tmp_path, "cpu-user-choice")
    assert gp.pack_switched_off_by_cpu_choice() is True


def test_enabling_it_flips_the_choice_without_touching_the_pack(gp, tmp_path):
    _install_fake_pack(tmp_path, "cpu-user-choice")
    before = sorted(p.name for p in (tmp_path / "runtime" / "gpu").rglob("*"))
    assert gp.enable_installed_pack() is True
    assert (tmp_path / "runtime" / ".gpu_choice").read_text() == "gpu-installed"
    assert gp.pack_switched_off_by_cpu_choice() is False
    assert sorted(p.name for p in (tmp_path / "runtime" / "gpu").rglob("*")) == before


def test_nothing_to_enable_without_a_pack(gp, tmp_path):
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / ".gpu_choice").write_text("cpu-user-choice")
    assert gp.pack_switched_off_by_cpu_choice() is False
    assert gp.enable_installed_pack() is False


def test_a_successful_install_records_the_gpu_choice(gp):
    import inspect
    src = inspect.getsource(gp._activate_staged_gpu_pack)
    ok = src.index('(dest / ".gpu_pack_ok").write_text')
    assert "record_gpu_choice(dest.parent)" in src[ok:]


@pytest.mark.parametrize("starter", ["def _start_gpu_pack_install(", "def _wiz_start_gpu_pack_install("])
def test_install_buttons_enable_an_existing_pack_before_downloading(starter):
    src = STARTUP.read_text(encoding="utf-8")
    i = src.index(starter)
    body = src[i:src.index("\n    def ", i + 10)]
    assert body.index("_enable_switched_off_pack(self)") < body.index("_GpuPackInstallThread(")
