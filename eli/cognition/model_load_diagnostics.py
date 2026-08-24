"""Say why a GGUF would not load — for ANY model, not a known list of them.

Loading `Qwen3.8-27B-Uncensored-Q4_K_M.gguf` reported this to the user:

    AttributeError: 'LlamaModel' object has no attribute 'sampler'

which is not the reason and mentions a component that was never involved. The
actual reason, visible only in llama.cpp's own log, was:

    llama_model_load: error loading model: missing tensor 'blk.64.ssm_conv1d.weight'

Two independent faults produced that:

1. llama-cpp-python's ``LlamaModel.__del__`` calls ``close()``, which reads
   ``self.sampler``. When ``__init__`` raises partway — exactly what a failed
   load does — that attribute was never assigned, so the destructor raises a
   second, unrelated exception that lands *after* the real one and reads like
   a sampler problem.
2. ELI constructs ``Llama(..., verbose=False)``, which silences llama.cpp
   entirely. The one line that says what is wrong is discarded before anyone
   can read it.

Nothing here is model-specific. It reads the architecture out of the GGUF
header, captures llama.cpp's log through the official callback, and turns
whatever llama.cpp said into a sentence with a remedy. A model this file has
never heard of gets the same treatment.
"""
from __future__ import annotations

import ctypes
import struct
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

_HARDENED = False
_hard_lock = threading.Lock()

# ctypes callbacks passed to C MUST outlive the C side's use of them. llama.cpp
# stores the raw function pointer; when the Python object backing it is garbage
# collected, the next log line calls freed memory and the process dies with a
# segfault that no Python handler can catch.
#
# This is not theoretical: a previous version of capture_llama_log() restored
# the log sink with `llama_log_set(llama_log_callback(lambda *a: None), ...)`,
# constructing the callback INLINE so it was freed the moment the statement
# finished. The next llama.cpp log line -- the first inference after a model
# load -- crashed the process. Both callbacks are therefore module-level and
# permanent, never rebuilt per call.
_LOG_SINK_LOCK = threading.Lock()
_LOG_CAPTURE_CB = None          # our capturing callback (installed while capturing)
_LOG_NULL_CB = None             # the no-op we restore to (never garbage collected)
_LOG_BUFFER: list = []          # capture target; swapped, never reallocated by C


class ModelLoadError(RuntimeError):
    """A GGUF could not be loaded, carrying the real reason and a remedy.

    RuntimeError rather than a bare Exception so existing broad handlers keep
    catching it; nothing in the tree catches the old ValueError specifically,
    so no caller loses its handler by this change.
    """


def harden_llama_destructor() -> bool:
    """Stop a failed load from raising a phantom 'sampler' AttributeError.

    Gives LlamaModel a class-level ``sampler = None`` so the destructor's
    ``self.sampler`` resolves even when ``__init__`` never reached the
    assignment. Purely additive: an instance that sets its own sampler shadows
    this and behaves exactly as before.
    """
    global _HARDENED
    with _hard_lock:
        if _HARDENED:
            return True
        try:
            from llama_cpp import _internals
            for cls_name in ("LlamaModel", "LlamaContext", "LlamaSampler"):
                cls = getattr(_internals, cls_name, None)
                if cls is not None and not hasattr(cls, "sampler"):
                    setattr(cls, "sampler", None)
            _HARDENED = True
            return True
        except Exception:
            log.debug("could not harden llama destructor", exc_info=True)
            return False


def gguf_architecture(path) -> Optional[str]:
    """``general.architecture`` from a GGUF header. Reads bytes only — no
    weights, no llama.cpp, no allocation. Returns None if unreadable."""
    try:
        with open(str(path), "rb") as f:
            if f.read(4) != b"GGUF":
                return None
            struct.unpack("<I", f.read(4))[0]          # version
            struct.unpack("<Q", f.read(8))[0]          # tensor count
            n_kv = struct.unpack("<Q", f.read(8))[0]

            def _str() -> str:
                n = struct.unpack("<Q", f.read(8))[0]
                return f.read(n).decode("utf-8", "replace")

            scalar = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i",
                      6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
            for _ in range(n_kv):
                key = _str()
                vtype = struct.unpack("<I", f.read(4))[0]
                if vtype == 8:
                    val = _str()
                    if key == "general.architecture":
                        return val
                elif vtype == 9:                        # array
                    etype = struct.unpack("<I", f.read(4))[0]
                    ln = struct.unpack("<Q", f.read(8))[0]
                    if etype == 8:
                        for _i in range(ln):
                            _str()
                    else:
                        f.read(struct.calcsize(scalar.get(etype, "I")) * ln)
                else:
                    f.read(struct.calcsize(scalar.get(vtype, "I")))
    except Exception:
        log.debug("gguf header read failed", exc_info=True)
    return None


@contextmanager
def capture_llama_log():
    """Collect llama.cpp's log lines regardless of ``verbose``.

    llama.cpp writes through its own C log callback, so redirecting Python's
    stderr does not see it and ``verbose=False`` throws it away. Installing a
    callback for the duration of the load is the only way to keep the one line
    that explains a failure.

    The callbacks are created once at module level and kept forever. A ctypes
    callback handed to C must never be garbage collected while C can still call
    it -- doing so is a use-after-free that segfaults the process. Only the
    BUFFER is swapped per call; the function pointers C sees never change.
    """
    global _LOG_CAPTURE_CB, _LOG_NULL_CB

    lines: list = []
    installed = False
    with _LOG_SINK_LOCK:
        try:
            import llama_cpp
            proto = getattr(llama_cpp, "llama_log_callback", None)
            setter = getattr(llama_cpp, "llama_log_set", None)
            if proto is not None and setter is not None:
                if _LOG_CAPTURE_CB is None:
                    def _cb(level, text, user_data):        # noqa: ARG001
                        # Runs inside llama.cpp's C callback. Logging from here
                        # could re-enter the callback being installed, so the
                        # failure is recorded in the buffer itself rather than
                        # through `log` -- observable, and safe from recursion.
                        try:
                            s = (text.decode("utf-8", "replace")
                                 if isinstance(text, bytes) else str(text))
                            if s:
                                _LOG_BUFFER.append(s)
                        except Exception as _cb_err:   # pragma: no cover
                            _LOG_BUFFER.append(
                                f"<log callback error: {type(_cb_err).__name__}>")
                    _LOG_CAPTURE_CB = proto(_cb)
                if _LOG_NULL_CB is None:
                    _LOG_NULL_CB = proto(lambda *_a: None)
                _LOG_BUFFER.clear()
                setter(_LOG_CAPTURE_CB, ctypes.c_void_p(0))
                installed = True
        except Exception:
            log.debug("llama log capture unavailable", exc_info=True)
    try:
        yield lines
    finally:
        if installed:
            with _LOG_SINK_LOCK:
                try:
                    import llama_cpp
                    # Restore the PERMANENT no-op, never a fresh temporary.
                    llama_cpp.llama_log_set(_LOG_NULL_CB, ctypes.c_void_p(0))
                except Exception:
                    log.debug("could not restore llama log callback", exc_info=True)
                lines.extend(_LOG_BUFFER)
                _LOG_BUFFER.clear()


def is_retryable_load_failure(log_lines) -> bool:
    """Whether retrying with different ctx/layers/batch could ever succeed.

    The adaptive ladder tried thirteen combinations against a model whose
    tensor set this build cannot read, failing identically every time and
    emitting a spurious sampler traceback on each one. Only resource failures
    change with the settings; a missing tensor, an unknown architecture and a
    corrupt file are properties of the file and the build, and no amount of
    reducing the context will alter them.

    Unknown failures are treated as retryable, so an unrecognised transient
    still gets its retries -- the ladder only stops when we are sure.
    """
    text = "\n".join(str(l) for l in (log_lines or [])).lower()
    if not text:
        return True
    terminal = ("missing tensor", "unknown model architecture",
                "unsupported model architecture", "invalid magic",
                "not a valid gguf", "wrong magic", "unexpected eof",
                "no such file", "failed to open")
    if any(k in text for k in terminal):
        return False
    return True


def _runtime_note() -> str:
    """The installed llama-cpp-python version, so a version-shaped failure names
    the version. Architecture support moves with the runtime, and "upgrade it"
    is not actionable without knowing what is installed."""
    try:
        import importlib.metadata as _md
        return f", llama-cpp-python {_md.version('llama-cpp-python')}"
    except Exception:
        log.debug("could not read llama-cpp-python version", exc_info=True)
        return ""


def explain_load_failure(exc: BaseException, log_lines, model_path,
                         *, gpu_layers: Optional[int] = None) -> str:
    """A sentence saying what went wrong and what to do about it.

    Classification is by what llama.cpp reported, not by model name, so it
    applies to any GGUF including ones released after this code was written.
    """
    text = "\n".join(str(l) for l in (log_lines or []))
    low = text.lower()
    name = Path(str(model_path)).name
    arch = gguf_architecture(model_path) or "unknown"

    # The precise llama.cpp line, if it emitted one.
    detail = ""
    for line in text.splitlines():
        if "error loading model" in line.lower() or "error:" in line.lower():
            detail = line.strip()
            break

    def _msg(body: str) -> str:
        tail = f"\n  llama.cpp said: {detail}" if detail else ""
        return f"{name} (architecture '{arch}'{_runtime_note()}) {body}{tail}"

    if "missing tensor" in low:
        missing = ""
        for line in text.splitlines():
            if "missing tensor" in line.lower():
                missing = line.split("missing tensor", 1)[1].strip(" :'\"")
                break
        hint = ""
        if any(k in missing.lower() for k in ("ssm_", "mamba", "conv1d")):
            hint = (" The missing tensor is a state-space (Mamba/SSM) layer, so this is a "
                    "hybrid attention+SSM model whose tensor layout this build predates.")
        return _msg(
            "could not load: this llama.cpp build knows the architecture but expects a "
            f"different tensor set, so the file is newer than the runtime.{hint} "
            "Upgrade the runtime (pip install -U llama-cpp-python) or use a GGUF "
            "converted for this build."
        )
    if "unknown model architecture" in low or "unsupported model architecture" in low:
        return _msg(
            "could not load: this llama.cpp build does not support that architecture at all. "
            "Upgrade with pip install -U llama-cpp-python, or pick a model whose "
            "architecture this build knows."
        )
    if any(k in low for k in ("out of memory", "cudamalloc", "failed to allocate",
                              "unable to allocate", "oom")):
        where = "VRAM" if (gpu_layers or 0) > 0 else "RAM"
        return _msg(
            f"ran out of {where} while loading. Lower the GPU layers or the context "
            f"size in Settings, close what else is using the {where}, or use a smaller "
            "quantisation."
        )
    if any(k in low for k in ("invalid magic", "not a valid gguf", "wrong magic",
                              "unexpected eof", "file too small")):
        return _msg(
            "is not a valid GGUF — the download is truncated or corrupt. Delete it and "
            "fetch it again, and check the file size against the source."
        )
    if "unsupported" in low or "not supported" in low:
        return _msg("could not load: llama.cpp reported an unsupported feature in this file.")
    return _msg(f"could not load. Underlying error: {type(exc).__name__}: {exc}")


__all__ = ["ModelLoadError", "harden_llama_destructor", "gguf_architecture",
           "capture_llama_log", "explain_load_failure",
           "is_retryable_load_failure"]
