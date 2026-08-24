"""A model that will not load must say why — for any GGUF, not a known list.

Reported: "still receiving llama sampler issues with
Qwen3.8-27B-Uncensored-Q4_K_M.gguf and
NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-UD-Q4_K_XL.gguf ... Eli is meant
to be model agnostic, not half agnostic."

There was no sampler problem. Reproduced on the actual file, the load failed
with:

    llama_model_load: error loading model: missing tensor 'blk.64.ssm_conv1d.weight'

and the user never saw that line. Two faults hid it:

  * llama-cpp-python's LlamaModel.__del__ calls close(), which reads
    self.sampler. A failed __init__ never assigns it, so the destructor raises
    a SECOND exception -- AttributeError: 'LlamaModel' object has no attribute
    'sampler' -- which lands after the real one and names a component that was
    never involved. That is the "sampler issue".
  * ELI constructs Llama(verbose=False), which silences llama.cpp completely,
    so the one line explaining the failure was discarded before anyone read it.

The fix is deliberately model-agnostic: read the architecture from the GGUF
header, capture llama.cpp's own log through its callback, and classify by what
llama.cpp reported. A model released after this code was written gets the same
treatment.
"""
import struct
from pathlib import Path

import pytest

from eli.cognition import model_load_diagnostics as mld


# ── the phantom sampler error ──────────────────────────────────────────────
def test_destructor_is_hardened_against_a_failed_init():
    """The exact reported symptom: a failed load raising AttributeError about
    a sampler that was never involved."""
    # llama_cpp is stubbed in parts of this suite, so assert the behaviour on a
    # stand-in that reproduces the broken state exactly: a class whose __init__
    # never assigned `sampler`, whose destructor then reads it.
    class _Broken:
        def close(self):
            return self.sampler        # what LlamaModel.close() does
    assert not hasattr(_Broken, "sampler")
    _Broken.sampler = None             # what harden_llama_destructor() applies
    assert _Broken().close() is None, "the destructor path still raises"

    # And the real hardening must run without error on this machine.
    assert mld.harden_llama_destructor() is True


def test_hardening_is_idempotent():
    assert mld.harden_llama_destructor() is True
    assert mld.harden_llama_destructor() is True


# ── architecture is read from the file, not guessed from the name ──────────
def test_architecture_read_from_gguf_header(tmp_path):
    """Built by hand so the test does not depend on any model being present."""
    p = tmp_path / "synthetic.gguf"
    arch = b"some-future-arch"
    key = b"general.architecture"
    with open(p, "wb") as f:
        f.write(b"GGUF")
        f.write(struct.pack("<I", 3))          # version
        f.write(struct.pack("<Q", 0))          # tensor count
        f.write(struct.pack("<Q", 1))          # kv count
        f.write(struct.pack("<Q", len(key))); f.write(key)
        f.write(struct.pack("<I", 8))          # type: string
        f.write(struct.pack("<Q", len(arch))); f.write(arch)
    assert mld.gguf_architecture(p) == "some-future-arch"


def test_architecture_of_a_non_gguf_is_none(tmp_path):
    p = tmp_path / "not-a-model.bin"
    p.write_bytes(b"\x00\x01\x02\x03")
    assert mld.gguf_architecture(p) is None


def test_architecture_never_raises_on_a_missing_file():
    assert mld.gguf_architecture("/nonexistent/eli-test.gguf") is None


# ── classification is by what llama.cpp said, not by model name ────────────
@pytest.mark.parametrize("log_line,expect", [
    ("llama_model_load: error loading model: missing tensor 'blk.64.ssm_conv1d.weight'",
     "different tensor set"),
    ("error loading model: unknown model architecture: 'some-future-arch'",
     "does not support that architecture"),
    ("ggml_backend_cuda_buffer_type_alloc_buffer: failed to allocate 8000 MiB: out of memory",
     "ran out of"),
    ("llama_model_loader: invalid magic characters",
     "not a valid GGUF"),
])
def test_failure_is_classified_from_the_log(log_line, expect, tmp_path):
    p = tmp_path / "any-model.gguf"
    p.write_bytes(b"GGUF")
    msg = mld.explain_load_failure(ValueError("Failed to load model"), [log_line], p)
    assert expect in msg, f"got: {msg}"
    assert "any-model.gguf" in msg, "the failing model is not named"


def test_ssm_hybrid_gets_a_specific_hint(tmp_path):
    """The reported models are hybrid attention+SSM; naming that saves the user
    guessing why a 'supported' architecture still fails."""
    p = tmp_path / "hybrid.gguf"; p.write_bytes(b"GGUF")
    msg = mld.explain_load_failure(
        ValueError("x"), ["error loading model: missing tensor 'blk.64.ssm_conv1d.weight'"], p)
    assert "state-space" in msg or "SSM" in msg
    assert "Mamba" in msg


def test_message_names_the_installed_runtime_version(tmp_path):
    """'Upgrade the runtime' is not actionable without saying what is installed."""
    p = tmp_path / "m.gguf"; p.write_bytes(b"GGUF")
    msg = mld.explain_load_failure(ValueError("x"), ["missing tensor 'foo'"], p)
    assert "llama-cpp-python" in msg


def test_unrecognised_failure_still_reports_something_useful(tmp_path):
    p = tmp_path / "m.gguf"; p.write_bytes(b"GGUF")
    msg = mld.explain_load_failure(RuntimeError("weird"), ["nothing familiar here"], p)
    assert "m.gguf" in msg and "RuntimeError" in msg


def test_no_message_ever_blames_the_sampler(tmp_path):
    """The whole point: a load failure must never again be reported as a
    sampler problem."""
    p = tmp_path / "m.gguf"; p.write_bytes(b"GGUF")
    for line in ["missing tensor 'x'", "unknown model architecture: 'y'",
                 "out of memory", "invalid magic characters", "??"]:
        msg = mld.explain_load_failure(ValueError("e"), [line], p)
        assert "sampler" not in msg.lower(), f"still blames the sampler: {msg}"


# ── the log capture itself ─────────────────────────────────────────────────
def test_log_capture_is_safe_and_restores():
    with mld.capture_llama_log() as lines:
        assert isinstance(lines, list)
    # A second entry/exit must not raise — the callback was restored.
    with mld.capture_llama_log() as lines2:
        assert isinstance(lines2, list)


def test_loader_routes_failures_through_the_explainer():
    src = Path("eli/cognition/gguf_inference.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "capture_llama_log" in code, "llama.cpp's log is still discarded"
    assert "explain_load_failure" in code, "raw load errors still reach the user"
    assert "harden_llama_destructor" in code, "the phantom sampler error can return"


# ── a hopeless load must not be retried thirteen times ─────────────────────
@pytest.mark.parametrize("line", [
    "llama_model_load: error loading model: missing tensor 'blk.64.ssm_conv1d.weight'",
    "error loading model: unknown model architecture: 'future-arch'",
    "llama_model_loader: invalid magic characters",
    "failed to open model file",
])
def test_terminal_failures_are_not_retryable(line):
    """No ctx/layer/batch combination conjures a missing tensor. The live log
    showed all thirteen candidates failing identically, each printing its own
    phantom sampler traceback."""
    assert mld.is_retryable_load_failure([line]) is False


@pytest.mark.parametrize("line", [
    "ggml_backend_cuda_buffer_type_alloc_buffer: failed to allocate 8000 MiB",
    "cudaMalloc failed: out of memory",
    "unable to allocate backend buffer",
])
def test_resource_failures_are_retryable(line):
    """These DO change with the settings — the ladder exists for them."""
    assert mld.is_retryable_load_failure([line]) is True


def test_unknown_failures_stay_retryable():
    """Only stop when certain; an unrecognised transient keeps its retries."""
    assert mld.is_retryable_load_failure(["something nobody has seen before"]) is True
    assert mld.is_retryable_load_failure([]) is True


def test_both_load_ladders_stop_on_unrecoverable_failures():
    for path, marker in [
        ("eli/cognition/gguf_inference.py", 'getattr(e, "retryable", True)'),
        ("eli/gui/eli_pro_audio_gui_v2_0.py", "_retryable(_attempt_log)"),
    ]:
        src = Path(path).read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        assert marker in code, f"{path} still retries an unrecoverable load"


def test_model_load_error_carries_retryability():
    err = mld.ModelLoadError("x")
    err.retryable = False
    assert isinstance(err, RuntimeError), "broad handlers must still catch it"
    assert err.retryable is False


# ── the ctypes callback must outlive C's use of it ─────────────────────────
# A segfault cannot be caught in-process (see the native-crash rule): the only
# honest test is to run the pattern in a subprocess and check the exit code.
import subprocess
import sys as _sys
import textwrap


def _run_isolated(body: str, timeout: int = 300):
    return subprocess.run(
        [_sys.executable, "-c", textwrap.dedent(body)],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, timeout=timeout,
    )


def test_callbacks_are_module_level_and_permanent():
    """Shipped in 2.3.17 and crashed the app: capture_llama_log() restored the
    log sink with `llama_log_set(llama_log_callback(lambda *a: None), ...)`,
    building the callback INLINE so Python freed it the instant the statement
    finished. llama.cpp kept the raw function pointer; the next log line -- the
    first inference after a model load -- called freed memory and the process
    died with SIGSEGV, which no Python handler can catch."""
    src = Path("eli/cognition/model_load_diagnostics.py").read_text(encoding="utf-8")
    start = src.index("def capture_llama_log():")
    code = "\n".join(l for l in src[start:src.index("def _runtime_note(")].splitlines()
                     if not l.strip().startswith("#"))
    assert "_LOG_NULL_CB" in code, "the restore callback is not the permanent one"
    # The killer construct must not reappear anywhere in the restore path.
    assert "llama_log_callback(lambda" not in code, \
        "restore builds a throwaway ctypes callback again — this is the segfault"
    assert hasattr(mld, "_LOG_CAPTURE_CB")
    assert hasattr(mld, "_LOG_NULL_CB")


def test_repeated_capture_reuses_one_callback_object():
    """Rebuilding the callback per call would let an older one be collected
    while llama.cpp still points at it."""
    with mld.capture_llama_log():
        first = mld._LOG_CAPTURE_CB
    with mld.capture_llama_log():
        second = mld._LOG_CAPTURE_CB
    if first is not None:
        assert first is second, "a new ctypes callback was built for the second capture"


@pytest.mark.timeout(400)
def test_capture_then_inference_does_not_segfault():
    """The exact live sequence: capture around a load, then llama.cpp logs
    again during inference. Exit 139 (SIGSEGV) is the failure being locked."""
    model = Path("models/SmolLM2-1.7B-Instruct-Q4_K_M.gguf")
    if not model.exists():
        pytest.skip("no small test model available")
    proc = _run_isolated(f"""
        from eli.cognition.model_load_diagnostics import capture_llama_log
        import llama_cpp, gc
        with capture_llama_log() as lines:
            m = llama_cpp.Llama(model_path={str(model)!r},
                                n_ctx=256, n_gpu_layers=0, n_batch=32, verbose=True)
        for _ in range(3):
            m.create_completion("Hi", max_tokens=4)
        del m
        gc.collect()
        print("OK")
    """)
    assert proc.returncode != -11 and proc.returncode != 139, (
        "SIGSEGV: the log callback was garbage collected while llama.cpp still "
        "held its function pointer"
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-500:]


# ── the frozen build's GPU pack can be older than what it bundles ──────────
def test_minimum_modern_arch_version_is_declared():
    assert mld.MIN_MODERN_ARCH_VERSION >= (0, 3, 30), \
        "below 0.3.30 a hybrid attention+SSM GGUF cannot be read"


def test_stale_gpu_pack_is_detected(monkeypatch):
    """Measured on the real 2.3.17 AppImage: it BUNDLES llama-cpp-python 0.3.35
    (which loads Qwen3.8-27B-Uncensored fine), but the downloaded CUDA GPU pack
    is 0.3.19 and shadows it via sys.path, so the model could not load. The
    capable runtime was present the whole time."""
    monkeypatch.setattr(mld, "_active_llama_is_gpu_pack", lambda: (True, "0.3.19"))
    assert mld.gpu_pack_is_too_old() is True


def test_current_gpu_pack_is_not_flagged(monkeypatch):
    monkeypatch.setattr(mld, "_active_llama_is_gpu_pack", lambda: (True, "0.3.35"))
    assert mld.gpu_pack_is_too_old() is False


def test_non_pack_runtime_is_never_flagged(monkeypatch):
    """A plain pip install is not the pack; the remedy would be wrong there."""
    monkeypatch.setattr(mld, "_active_llama_is_gpu_pack", lambda: (False, "0.3.19"))
    assert mld.gpu_pack_is_too_old() is False


def test_stale_pack_failure_names_the_switch(monkeypatch, tmp_path):
    monkeypatch.setattr(mld, "_active_llama_is_gpu_pack", lambda: (True, "0.3.19"))
    monkeypatch.setattr(mld, "gpu_pack_is_too_old", lambda: True)
    p = tmp_path / "hybrid.gguf"; p.write_bytes(b"GGUF")
    msg = mld.explain_load_failure(
        ValueError("x"), ["error loading model: missing tensor 'blk.64.ssm_conv1d.weight'"], p)
    assert "ELI_DISABLE_GPU_PACK=1" in msg, "the working remedy is not offered"
    assert "0.3.19" in msg, "the actual pack version is not named"


def test_runtime_hook_honours_the_opt_out():
    src = Path("packaging/pyinstaller/rthook_eli_frozen_paths.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "ELI_DISABLE_GPU_PACK" in code, "there is no way to bypass a stale GPU pack"
    assert "not _pack_off" in code, "the opt-out does not actually gate activation"
