"""A GPU pack must never leave a user worse off than no pack at all.

Shipped defect, seen on a machine whose GPU worked minutes earlier:

    [21:20:17] llama.cpp GPU offload support: False
    [21:20:17] GPU offload unavailable at runtime -> forcing CPU-safe tuning
               (gpu_layers=0, batch<=128)

The tuner had already computed the right answer in the same log --
"gpu_layers=29 for 6442MB free VRAM" -- and then forced 0 because the runtime
said offload was unavailable.

Cause: `preload_native_libs()` preloaded only the CUDA libraries. A Vulkan pack
needs the system Vulkan LOADER (libvulkan.so.1), which the pack cannot ship
because it belongs to the GPU driver. Outside the bundle it resolved normally;
inside, where LD_LIBRARY_PATH points at the app's own libraries, it did not, so
ggml dropped the Vulkan backend. The pack then shadowed a BUNDLED runtime that
was both newer and able to run the model -- the user lost the GPU *and* model
support in one step.

Two independent layers now prevent that, because this ships to arbitrary users
on arbitrary hardware and neither layer alone is enough:

  1. install time  -- a pack that cannot offload is rejected and deleted.
  2. every start   -- a pack that cannot offload HERE is unloaded and the
                      bundled runtime takes over. Install-time checks run in
                      the installing shell; the app runs inside the bundle,
                      and those are different environments.
"""
import re
from pathlib import Path

import pytest

PACK = Path("packaging/pyinstaller/eli_gpu_pack.py")
HOOK = Path("packaging/pyinstaller/rthook_eli_frozen_paths.py")


def _code(p: Path) -> str:
    return "\n".join(l for l in p.read_text(encoding="utf-8").splitlines()
                     if not l.strip().startswith("#"))


# ── the Vulkan loader must be preloaded, not just CUDA ─────────────────────
def test_preloader_loads_the_vulkan_loader():
    code = _code(PACK)
    body = code[code.index("def preload_native_libs"):]
    assert "libvulkan.so.1" in body, \
        "only the CUDA libs are preloaded; a Vulkan pack cannot bind its loader"
    assert "find_library" in body, "no portable lookup for the driver's loader"


def test_preloader_loads_the_ggml_backends():
    """A backend that cannot find libggml-base is skipped silently, which is
    indistinguishable from 'this machine has no GPU'."""
    body = _code(PACK)
    body = body[body.index("def preload_native_libs"):]
    for lib in ("libggml-base.so*", "libggml-vulkan.so*", "libggml-cuda.so*"):
        assert lib in body, f"{lib} is not preloaded"


def test_windows_preloads_the_vulkan_runtime_too():
    body = _code(PACK)
    body = body[body.index("def preload_native_libs"):]
    assert "vulkan-1.dll" in body


# ── layer 1: install must prove offload, not just import ───────────────────
def test_install_verify_requires_actual_offload():
    body = _code(PACK)
    probe = body[body.index("def _verify("):]
    assert "llama_supports_gpu_offload()" in probe, \
        "install verification still passes a pack that cannot use the GPU"
    assert "gpu-pack-verify-no-offload" in probe


def test_install_verify_preloads_vulkan_before_probing():
    """The probe must set up the same environment the app will, or it proves
    nothing about the app."""
    body = _code(PACK)
    probe = body[body.index("def _verify("):]
    assert "libvulkan.so.1" in probe
    assert "libggml-base.so*" in probe


def test_a_pack_that_cannot_offload_is_removed_and_explained():
    body = PACK.read_text(encoding="utf-8")
    assert "shadow the bundled" in body, \
        "the failure message does not say why keeping the pack would be worse"


# ── layer 2: every start must re-prove it, in THIS environment ─────────────
def test_activation_verifies_offload_in_this_environment():
    code = _code(HOOK)
    assert "llama_supports_gpu_offload()" in code, \
        "the pack is activated on an install-time marker alone"
    assert "_pack_live" in code


def test_a_dead_pack_is_removed_from_path_and_module_cache():
    """Dropping it from sys.path is not enough: the already-imported copy would
    keep serving from sys.modules."""
    code = _code(HOOK)
    assert "sys.path.remove" in code
    assert "sys.modules.pop" in code
    assert 'k.startswith("llama_cpp.")' in code


def test_fallback_tells_the_user_what_happened():
    body = HOOK.read_text(encoding="utf-8")
    assert "falling back to the bundled runtime" in body
    assert "--install-gpu-pack --force" in body, "no remedy offered"


def test_the_opt_out_still_exists():
    """A user must still be able to bypass a pack deliberately."""
    assert "ELI_DISABLE_GPU_PACK" in _code(HOOK)


# ── live: the pack installed on this machine must satisfy the contract ─────
def test_installed_pack_reports_offload_after_preload():
    import sys
    gpu_dir = Path.home() / ".local/share/ELI_v2/runtime/gpu"
    if not (gpu_dir / "llama_cpp").is_dir():
        pytest.skip("no GPU pack installed on this machine")
    sys.path.insert(0, str(PACK.parent))
    import eli_gpu_pack
    eli_gpu_pack.preload_native_libs(gpu_dir)
    ok, detail = eli_gpu_pack._verify(gpu_dir)
    assert ok, f"the installed pack fails its own contract: {detail[:200]}"


# ── layer 3: a pack that cannot READ the model must step aside by itself ───
# The first two layers cover a pack that cannot offload. This covers the other
# way a pack strands a user: it drives the GPU perfectly but predates the
# model's architecture (a CUDA pack from an index that stops at 0.3.19 cannot
# read hybrid attention+SSM GGUFs). Telling the user to set an environment
# variable is not a fix for software that ships to people who will never read
# the message -- the loader retries on the bundled runtime instead.
def test_deactivate_gpu_pack_exists():
    from eli.cognition import model_load_diagnostics as mld
    assert hasattr(mld, "deactivate_gpu_pack")


def test_deactivation_clears_path_and_module_cache():
    import inspect
    from eli.cognition import model_load_diagnostics as mld
    src = inspect.getsource(mld.deactivate_gpu_pack)
    assert "_sys.path.remove" in src
    assert "_sys.modules.pop" in src, \
        "the imported copy would keep serving after the path is cleared"


def test_deactivation_is_a_noop_when_no_pack_is_active(monkeypatch):
    """Must be safe to call on a plain pip install with no pack at all."""
    import sys as _s
    from eli.cognition import model_load_diagnostics as mld
    monkeypatch.setattr(_s, "path", [p for p in _s.path if "runtime/gpu" not in p])
    assert mld.deactivate_gpu_pack() is False


def test_loader_retries_on_the_bundle_instead_of_instructing_the_user():
    src = Path("eli/cognition/gguf_inference.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "deactivate_gpu_pack" in code, \
        "an unreadable-model failure still ends in an error instead of a retry"
    assert "gpu_pack_is_too_old" in code, "the retry is not conditioned on the pack"


def test_the_bundle_retry_is_not_attempted_for_recoverable_failures():
    """OOM must keep using the adaptive ladder; dropping the GPU for it would
    turn a settings problem into a permanent slowdown."""
    src = Path("eli/cognition/gguf_inference.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "not _retryable(_load_log) and _pack_old()" in code
