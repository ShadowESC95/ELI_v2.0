"""One sizing authority, and an installer that runs off x86.

``recommend()`` called the joint fit and then overwrote its batch twelve lines later, so
``ELI_TARGET_BATCH`` could only ever LOWER the value and a dialog set to 512 stored 128.

And ``install.sh`` emitted ``-march=x86-64`` on every architecture, so no ARM host
could build the inference engine at all.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from eli.core import hardware_profile as hp
from eli.core.hardware_profile import HardwareProfile, recommend

REPO = Path(__file__).resolve().parent.parent


def _hw(free_mb: int = 6168, total_mb: int = 7752) -> HardwareProfile:
    return HardwareProfile(
        cpu_threads=12, ram_gb=33.5, available_ram_gb=18.9, has_gpu=True,
        gpu_name="test GPU", free_vram_mb=free_mb, total_vram_mb=total_mb,
        vram_gb=total_mb / 1024.0,
    )


def _models(size_gb: float = 4.68):
    return [{"name": "test.gguf", "path": "/tmp/test.gguf", "size_gb": size_gb}]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setattr(hp, "_llama_gpu_offload_available", lambda: True)
    for var in ("ELI_VRAM_RESERVE_MB", "ELI_FORCE_GPU_LAYERS",
                "ELI_MIN_BATCH", "ELI_TARGET_BATCH"):
        monkeypatch.delenv(var, raising=False)


def test_gui_app_does_not_restate_the_kv_formula():
    src = (REPO / "eli/gui/app.py").read_text(encoding="utf-8")
    assert "_KV_BYTES_PER_TOKEN_PER_LAYER = " not in src, "a third copy of the constant"
    assert "from eli.core.hardware_profile import" in src


# ── the operator's batch is a target, not a ceiling ──────────────────────────
def test_target_batch_is_honoured_when_the_heuristic_would_go_lower(monkeypatch):
    """Partial offload interpolates well below 512; an explicit target must win."""
    monkeypatch.setenv("ELI_TARGET_BATCH", "512")
    rec = recommend(_hw(free_mb=6168), _models(4.68))
    assert rec.batch_size >= 128
    assert any("your target" in r or "compute buffer" in r for r in rec.reasoning), (
        f"neither the target nor a measured reduction was explained: {rec.reasoning}"
    )


def test_target_batch_survives_as_the_anchor_when_headroom_allows(monkeypatch):
    """A big card has room, so a 512 target must not be silently reduced."""
    monkeypatch.setenv("ELI_TARGET_BATCH", "512")
    rec = recommend(_hw(free_mb=40000, total_mb=49152), _models(4.68))
    assert rec.batch_size == 512


def test_the_late_cap_that_could_only_lower_batch_is_gone():
    src = inspect.getsource(recommend)
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "_env_batch_cap" not in code, "the cap-only ELI_TARGET_BATCH block survived"


def test_the_batch_overwrite_no_longer_discards_the_target():
    """The offload heuristic must not run when the operator set a target."""
    src = inspect.getsource(recommend)
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "if _env_target_batch > 0:" in code, "the target is not the first branch"


# ── one VRAM reserve ─────────────────────────────────────────────────────────
def test_the_dynamic_budget_uses_the_shared_reserve():
    from eli.core import dynamic_runtime_budget as drb
    src = inspect.getsource(drb.derive_budget)
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "- 900" not in code, "a fourth private VRAM reserve survived"
    assert "vram_reserve_mb" in code


# ── the installer runs off x86 ───────────────────────────────────────────────
def _install_sh_flag_fn() -> str:
    """Executable lines of the flag helper — comments describe the old bug by name."""
    src = (REPO / "install.sh").read_text(encoding="utf-8")
    m = re.search(r"^_llama_safe_cpu_cmake_flags\(\)\s*\{.*?^\}", src, re.S | re.M)
    assert m, "_llama_safe_cpu_cmake_flags not found in install.sh"
    return "\n".join(l for l in m.group(0).splitlines()
                     if not l.strip().startswith("#"))


def test_install_sh_does_not_hand_arm_an_x86_march():
    fn = _install_sh_flag_fn()
    assert "aarch64|arm64)" in fn, "no 64-bit ARM branch"
    assert "armv8-a" in fn, "ARM gets no baseline ISA"
    assert "Darwin" in fn, "Apple clang rejects -march for arm64; no Darwin branch"
    # Every -march= must sit inside a case branch that named its architecture:
    # the x86 spelling must never be reachable as the catch-all again.
    x86_branch = fn.split("x86_64|amd64)", 1)[1].split(";;", 1)[0]
    assert x86_branch.count("-march=x86-64") == 6, "x86 baselines moved out of their branch"
    outside = fn.replace(x86_branch, "")
    assert "-march=x86-64" not in outside, "an x86 flag is reachable from a non-x86 branch"
    # The wildcard branch must compile anywhere: no ISA flag at all.
    wildcard = fn.split("ppc64le|riscv64|s390x|*)", 1)[1].split(";;", 1)[0]
    assert "-march=" not in wildcard, "unknown architectures still get an ISA flag"
    assert "GGML_NATIVE=OFF" in wildcard


def test_llama_cpu_compat_flags_agree_with_the_installer():
    from eli.core.llama_cpu_compat import safe_source_cmake_flags
    src = inspect.getsource(safe_source_cmake_flags)
    for arch in ("aarch64", "arm64", "armv8-a", "darwin"):
        assert arch in src.lower(), f"{arch} unhandled — the two paths have drifted"


@pytest.mark.parametrize("machine,expect_absent", [("aarch64", "x86-64"), ("arm64", "x86-64")])
def test_arm_never_receives_an_x86_flag(monkeypatch, machine, expect_absent):
    import eli.core.llama_cpu_compat as lcc
    monkeypatch.setattr(lcc.platform, "machine", lambda: machine)
    monkeypatch.setattr(lcc.sys, "platform", "linux")
    assert expect_absent not in lcc.safe_source_cmake_flags()


# ── Windows parity ───────────────────────────────────────────────────────────
def test_windows_installer_measures_runtime_init():
    """install.sh proves llama_backend_init(); install.ps1 must too."""
    ps1 = (REPO / "install.ps1").read_text(encoding="utf-8")
    assert "llama_backend_init" in ps1, "Windows never measures runtime init (SIGILL ships silently)"
    assert "force-reinstall" in ps1, "no fallback when the wheel will not start"


def test_windows_installer_warns_on_low_ram():
    ps1 = (REPO / "install.ps1").read_text(encoding="utf-8")
    assert "ramGb" in ps1 and "-le 8" in ps1, "no low-RAM guidance on Windows"


# ── frozen builds fail loudly, not silently ──────────────────────────────────
def test_frozen_entry_proves_the_cpu_before_loading_the_gui():
    entry = (REPO / "packaging/pyinstaller/eli_entry.py").read_text(encoding="utf-8")
    assert "_verify_cpu_runtime()" in entry, "frozen builds still SIGILL with no message"
    body = entry.split("def _verify_cpu_runtime", 1)[1].split("\ndef ", 1)[0]
    assert "runtime_smoke_test" in body, "the check does not measure init"
    assert "ELI_DISABLE_GPU_PACK" in body, (
        "the retry cannot reach the child process without the env switch"
    )
    assert ".gpu_choice" in body, "the CPU fallback is not persisted for the next launch"
    assert ".cpu_runtime_ok" in body, (
        "the verdict is not cached — every frozen launch would pay a process spawn"
    )
    assert ".gpu_pack_ok" in body, (
        "the cached verdict is not invalidated when the GPU pack changes"
    )
