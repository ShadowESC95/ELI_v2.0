"""One sizing authority, and an installer that runs off x86.

Three engines were computing ctx / GPU layers / batch with DIFFERENT arithmetic,
so the startup preview, the tuning panel and the loaded model reported three
numbers for one machine at one moment:

  * ``startup_hardware_optimizer.kv_cache_mb`` used 1024 B/token/layer while
    ``hardware_profile._kv_cache_mb`` used 6000 (1500 at q4) — a 46% under-estimate
    in the engine that powers the load ladder's live-tuner rung.
  * ``recommend()`` called the joint fit and then overwrote its batch twelve lines
    later, so ``ELI_TARGET_BATCH`` could only ever LOWER the value and a dialog set
    to 512 stored 128.
  * ``load_probe`` allowed a flat 30s regardless of model size, so a 8.89GB model at
    ctx=10384 was structurally unprovable and the operator's GPU layers lost every
    launch to the fallback.

And ``install.sh`` emitted ``-march=x86-64`` on every architecture, so no ARM host
could build the inference engine at all.
"""
from __future__ import annotations

import ast
import inspect
import re
import textwrap
from pathlib import Path

import pytest

from eli.core import hardware_profile as hp
from eli.core import startup_hardware_optimizer as sho
from eli.core.hardware_profile import HardwareProfile, _kv_cache_mb, recommend

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


# ── one KV formula ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("n_ctx,layers", [(2048, 32), (10384, 32), (12288, 48), (32768, 80)])
def test_the_optimizer_uses_the_loaders_kv_arithmetic(n_ctx, layers):
    """allocate() and the load ladder must budget the same KV cache."""
    assert sho.kv_cache_mb(n_ctx, layers) == _kv_cache_mb(n_ctx, layers, quant=True)
    assert sho.kv_cache_mb(n_ctx, layers, quant=False) == _kv_cache_mb(n_ctx, layers, quant=False)


def test_the_1024_byte_kv_constant_is_gone():
    """Match executable lines only — the docstring names the old constant on purpose."""
    src = inspect.getsource(sho.kv_cache_mb)
    body = ast.parse(textwrap.dedent(src)).body[0]
    stmts = [s for s in body.body if not isinstance(s, ast.Expr)
             or not isinstance(getattr(s, "value", None), ast.Constant)]
    code = "\n".join(ast.unparse(s) for s in stmts)
    assert "1048576" not in code and "1024" not in code, (
        f"the local q4 approximation survived: {code}")
    assert "_kv_cache_mb" in code, "kv_cache_mb no longer delegates to the canonical math"


def test_per_layer_vram_matches_the_fit():
    """hardware_profile divides by layers + 2 for embedding/output tensors."""
    model_gb, layers = 4.68, 32
    assert sho.layer_mb(model_gb, layers) == pytest.approx(
        (model_gb * 1024.0) / (layers + 2))


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


# ── the probe budget scales with the work ────────────────────────────────────
def test_probe_timeout_scales_with_model_size(tmp_path, monkeypatch):
    from eli.core import load_probe as lp
    monkeypatch.delenv("ELI_LOAD_PROBE_TIMEOUT", raising=False)

    small = tmp_path / "small.gguf"
    small.write_bytes(b"\0" * (1024 * 1024))
    big = tmp_path / "big.gguf"
    big.write_bytes(b"\0" * (256 * 1024 * 1024))

    t_small = lp.probe_timeout_for(str(small), 4096)
    t_big = lp.probe_timeout_for(str(big), 10384)
    assert t_big > t_small, "a larger model at a larger ctx got no more time"
    assert t_small >= 30.0


def test_probe_timeout_is_bounded_and_overridable(tmp_path, monkeypatch):
    from eli.core import load_probe as lp
    huge = tmp_path / "huge.gguf"
    huge.write_bytes(b"\0")
    monkeypatch.delenv("ELI_LOAD_PROBE_TIMEOUT", raising=False)
    assert lp.probe_timeout_for(str(huge), 1_000_000) <= lp._TIMEOUT_CEILING_S
    monkeypatch.setenv("ELI_LOAD_PROBE_TIMEOUT", "7")
    assert lp.probe_timeout_for(str(huge), 10384) == 7.0


def test_a_nine_gigabyte_model_gets_more_than_the_old_flat_budget(tmp_path, monkeypatch):
    """The live Ornith-9B case: 30s could never cover load + 4672-token prefill."""
    from eli.core import load_probe as lp
    monkeypatch.delenv("ELI_LOAD_PROBE_TIMEOUT", raising=False)
    model = tmp_path / "ornith-9b-q8.gguf"
    # Sparse: real st_size, no 9GB written, and Path.stat left alone so pytest's
    # own traceback machinery keeps working.
    with open(model, "wb") as fh:
        fh.truncate(int(8.89 * 1024 ** 3))
    budget = lp.probe_timeout_for(str(model), 10384)
    assert budget > 120.0, f"still unprovable at {budget:.0f}s"
    assert budget <= lp._TIMEOUT_CEILING_S


def test_a_timeout_is_remembered_briefly_but_never_as_a_verdict():
    from eli.core import load_probe as lp
    src = inspect.getsource(lp.probe_verdict)
    assert "_recently_timed_out" in src, "a slow config re-pays the full budget every launch"
    assert "_record_timeout" in src
    record_src = inspect.getsource(lp._record_timeout)
    assert '"ok"' not in record_src, "a timeout was cached as a pass/fail verdict"


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
