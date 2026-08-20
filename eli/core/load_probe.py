"""Verify a set of load parameters actually works, without dying if it doesn't.

The operator's settings are the priority. The only honest way to keep that
promise is to find out whether they work on THIS machine — not to guess, and not
to quietly reduce them.

Guessing is what shipped. The loader queued the requested numbers first on the
reasoning that hardware which cannot honour them would refuse, costing one
failed attempt before the fallbacks took over. llama.cpp/CUDA allocate LAZILY,
so there is no refusal: the load reports success, wins the ladder, and the
process is killed later by an abort() inside the CUDA backend, mid-generation.
Live at 2.2.7 on a 6268MB-free card:

    attempt 1/13: requested (ctx=10384 gpu_layers=99 batch=128)
    selected=requested (ctx=10384 gpu_layers=99 batch=128)
    ✅ Model loaded successfully
    ...
    prompt_tokens=5189
    ggml-cuda.cu:98: CUDA error  ->  Aborted (core dumped)

A Python process cannot catch its own abort(). It can, however, watch a CHILD
process take one. So the candidate parameters are loaded in a subprocess which
drives a real decode through them; the parent reads the exit status and knows.

That turns "cannot be honoured" from an assumption into a measurement, which is
what the fallback ladder needed all along.

Nothing here caps, substitutes or hardcodes a parameter. The probe reports
pass/fail on the numbers it is given. Its own working sizes derive from the
caller's context. The verdict is cached per (model, parameters, GPU identity),
so a configuration is proven once rather than on every startup, and a machine
whose free VRAM has changed is re-proven rather than trusting a stale pass.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

# A probe blocks startup, so it gets a budget an operator would tolerate rather
# than one that is certain to finish. 300s was the first value shipped and it was
# wrong: on a configuration whose layers spill to CPU the probe decode runs at
# CPU speed, and a live 2.2.8 launch sat at "attempt 1/13" for three and a half
# minutes with nothing on screen explaining why. Past this budget the answer is
# "unproven", the operator's settings stand, and startup continues.
# 60s was the second value and still too long in practice: a 2.3.8 launch spent the
# full minute proving 99 GPU layers on a 2060 Super, timed out "unproven", and fell
# back to the 26 layers smart-fit had already measured — so the operator paid a
# minute of blank startup for an answer the fallback had. 30s keeps the probe useful
# for the configurations it can settle quickly while halving the cost of the ones it
# cannot.
# Override with ELI_LOAD_PROBE_TIMEOUT.
_DEFAULT_TIMEOUT_S = 30.0

# Verdicts older than this are re-proven — drivers, other GPU tenants and
# resident models all move. Override with ELI_LOAD_PROBE_TTL.
_DEFAULT_TTL_S = 7 * 24 * 3600.0


def _cache_path() -> Path:
    from eli.core.paths import get_paths
    p = Path(get_paths().artifacts_dir) / "runtime" / "load_probe.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


_gpu_identity_memo: Optional[str] = None


def _gpu_identity() -> str:
    """Name + total VRAM. Free VRAM is deliberately excluded: it moves minute to
    minute, and keying on it would make every verdict a miss.

    Memoised per process: this is on the startup path and is consulted for every
    cache lookup AND every record, each of which was otherwise shelling out to
    nvidia-smi. The card does not change while ELI is running.
    """
    global _gpu_identity_memo
    if _gpu_identity_memo is not None:
        return _gpu_identity_memo
    try:
        from eli.core.startup_hardware_optimizer import detect_nvidia_gpus, select_gpu
        gpu = select_gpu(detect_nvidia_gpus())
        if gpu:
            _gpu_identity_memo = f"{getattr(gpu, 'name', '?')}|{getattr(gpu, 'total_mb', 0)}"
            return _gpu_identity_memo
    except Exception:
        log.debug("load_probe: GPU identity unavailable", exc_info=True)
    _gpu_identity_memo = "cpu"
    return _gpu_identity_memo


def _key(model_path: str, n_ctx: int, n_gpu_layers: int, n_batch: int) -> str:
    raw = "|".join([
        str(model_path), str(int(n_ctx)), str(int(n_gpu_layers)),
        str(int(n_batch)), _gpu_identity(),
    ])
    try:
        size = Path(model_path).stat().st_size
    except Exception:
        size = 0
    raw += f"|{size}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _load_cache() -> Dict[str, Any]:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    try:
        _cache_path().write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        log.debug("load_probe: cache write failed", exc_info=True)


def cached_verdict(model_path: str, n_ctx: int, n_gpu_layers: int,
                   n_batch: int) -> Optional[bool]:
    """A previously proven verdict for these parameters, or None."""
    ttl = float(os.environ.get("ELI_LOAD_PROBE_TTL", "") or _DEFAULT_TTL_S)
    entry = _load_cache().get(_key(model_path, n_ctx, n_gpu_layers, n_batch))
    if not isinstance(entry, dict):
        return None
    if time.time() - float(entry.get("ts", 0) or 0) > ttl:
        return None
    ok = entry.get("ok")
    return bool(ok) if isinstance(ok, bool) else None


def _record(model_path: str, n_ctx: int, n_gpu_layers: int, n_batch: int,
            ok: bool, detail: str = "") -> None:
    cache = _load_cache()
    cache[_key(model_path, n_ctx, n_gpu_layers, n_batch)] = {
        "ok": bool(ok),
        "ts": time.time(),
        "model": str(model_path),
        "n_ctx": int(n_ctx),
        "n_gpu_layers": int(n_gpu_layers),
        "n_batch": int(n_batch),
        "gpu": _gpu_identity(),
        "detail": str(detail)[:300],
    }
    _save_cache(cache)


# The child. Kept as source rather than a module entry point so the probe works
# identically from a source checkout and from a PyInstaller bundle, where a
# `-m eli.core.load_probe` invocation is not available.
_CHILD = r'''
import json, sys
cfg = json.loads(sys.argv[1])
try:
    from llama_cpp import Llama
except Exception as e:
    print("IMPORT_FAIL:%s" % e, file=sys.stderr)
    raise SystemExit(3)
try:
    llm = Llama(
        model_path=cfg["model_path"],
        n_ctx=int(cfg["n_ctx"]),
        n_gpu_layers=int(cfg["n_gpu_layers"]),
        n_batch=int(cfg["n_batch"]),
        verbose=False,
        logits_all=False,
    )
except Exception as e:
    print("LOAD_FAIL:%s" % e, file=sys.stderr)
    raise SystemExit(4)
# Drive a real decode. Loading alone proves nothing: the 2.2.7 abort happened
# with the model already resident and the context already created. What was
# never allocated until generation is the compute buffer for a large prompt,
# so the probe must push a prompt of the size the caller will really use.
try:
    prompt = "word " * int(cfg["probe_tokens"])
    out = llm(prompt, max_tokens=int(cfg["probe_gen"]), echo=False)
    _ = (out or {}).get("choices", [{}])[0].get("text", "")
except Exception as e:
    print("DECODE_FAIL:%s" % e, file=sys.stderr)
    raise SystemExit(5)
print("PROBE_OK")
raise SystemExit(0)
'''


# Verdicts. The caller needs the difference between "proved fine" and "could not
# prove anything", because it is deciding whether to load a configuration that
# measurement already says does not fit.
PROVEN_OK = "ok"            # ran, survived a real decode
PROVEN_BAD = "bad"          # ran, failed (this is what the CUDA abort looks like)
UNPROVEN_TIMEOUT = "timeout"      # ran, did not finish in the budget
UNPROVEN_UNAVAILABLE = "unavailable"  # could not run at all — no information
SKIPPED = "skipped"         # nothing to prove (cpu-only, disabled)


def probe_verdict(model_path: str, n_ctx: int, n_gpu_layers: int, n_batch: int,
                  *, use_cache: bool = True,
                  timeout_s: Optional[float] = None) -> Tuple[str, str]:
    """Do these exact parameters survive a real decode on this machine?

    Returns ``(verdict, detail)`` where verdict is one of the constants above.
    Never raises, and never modifies the parameters — the caller decides.

    Why three states and not a bool: collapsing "could not prove" into "fine"
    is what shipped the 2.2.9 crash. The probe only runs when the request
    ALREADY exceeds the measured fit, so on that path "unproven" is not a
    neutral result — proceeding is a gamble whose downside is a CUDA abort()
    that takes the whole process down mid-generation. The caller now
    distinguishes a timeout (the probe ran and did not finish — fall back to
    the measured rungs) from an unavailable probe (no information at all —
    the operator's settings stand, as before).
    """
    if os.environ.get("ELI_LOAD_PROBE", "1").strip().lower() in ("0", "false", "no"):
        return SKIPPED, "probe disabled (ELI_LOAD_PROBE=0)"

    n_ctx, n_gpu_layers, n_batch = int(n_ctx), int(n_gpu_layers), int(n_batch)

    if use_cache:
        cached = cached_verdict(model_path, n_ctx, n_gpu_layers, n_batch)
        if cached is not None:
            return (PROVEN_OK if cached else PROVEN_BAD), "cached verdict"

    # CPU-only configurations cannot hit the CUDA abort this exists to catch,
    # and a probe would cost a full cold load for nothing.
    if n_gpu_layers <= 0:
        return SKIPPED, "cpu-only: no GPU allocation to prove"

    # Probe sizes derive from the caller's own parameters — no magic numbers.
    #
    # It must be a prompt of the size ELI will really send. A cheaper probe was
    # tried — four batches instead of a fraction of the window — on the theory
    # that llama.cpp reaches its peak allocation on the first decode regardless
    # of prompt length. Measurement says otherwise, and the operator's own logs
    # are the proof: on one unchanged configuration, 2.2.4-2.2.6 ran first
    # prompts of ~2147 tokens without trouble and 2.2.7 aborted at 5189. A short
    # probe would have passed every one of those startups and the crash would
    # have shipped anyway.
    #
    # So the cost is accepted where it buys an answer, and bounded by the
    # timeout above rather than by making the question easier.
    probe_tokens = max(256, int(n_ctx * 0.45))
    probe_gen = max(8, min(32, int(n_ctx * 0.01)))

    timeout = float(timeout_s if timeout_s is not None
                    else (os.environ.get("ELI_LOAD_PROBE_TIMEOUT", "")
                          or _DEFAULT_TIMEOUT_S))
    payload = json.dumps({
        "model_path": str(model_path),
        "n_ctx": n_ctx,
        "n_gpu_layers": n_gpu_layers,
        "n_batch": n_batch,
        "probe_tokens": probe_tokens,
        "probe_gen": probe_gen,
    })

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD, payload],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # Slow, not proven broken. Do not override the operator on a timeout,
        # and do not cache a verdict that was never reached.
        log.debug("[LOAD_PROBE] timed out after %.0fs — treating as unproven", timeout)
        return UNPROVEN_TIMEOUT, f"probe timed out after {timeout:.0f}s (unproven)"
    except Exception as e:
        log.debug("[LOAD_PROBE] could not run: %s", e)
        return UNPROVEN_UNAVAILABLE, f"probe unavailable: {e}"

    elapsed = time.perf_counter() - t0
    rc = int(proc.returncode or 0)
    # Prefer the child's own marker line. llama_cpp's LlamaModel.__del__ raises
    # `AttributeError: 'LlamaModel' object has no attribute 'sampler'` when a
    # constructor fails part-way, and that lands AFTER the real message — so
    # taking the last stderr line reported the destructor's noise instead of
    # "Failed to load model from file", which is the answer that matters.
    _stderr = (proc.stderr or "").strip()
    tail = ""
    for _marker in ("LOAD_FAIL:", "DECODE_FAIL:", "IMPORT_FAIL:"):
        for _line in _stderr.splitlines():
            if _line.startswith(_marker):
                tail = _line[:220]
                break
        if tail:
            break
    if not tail:
        _lines = [l for l in _stderr.splitlines() if l.strip()]
        tail = _lines[-1][:220] if _lines else ""

    if rc == 0 and "PROBE_OK" in (proc.stdout or ""):
        _record(model_path, n_ctx, n_gpu_layers, n_batch, True, "ok")
        log.debug("[LOAD_PROBE] ctx=%d layers=%d batch=%d verified in %.1fs",
                  n_ctx, n_gpu_layers, n_batch, elapsed)
        return PROVEN_OK, f"verified in {elapsed:.1f}s"

    if rc == 3:
        # llama_cpp missing in the child — the check could not run.
        return UNPROVEN_UNAVAILABLE, "llama_cpp unavailable in probe (unproven)"

    if rc == -15:
        # SIGTERM: something outside asked the probe to stop. That says nothing
        # about the configuration, so it must not be recorded as a verdict —
        # otherwise a shutdown, a supervisor, or an operator killing a slow
        # probe would permanently condemn settings that were never tested.
        # SIGABRT/SIGSEGV/SIGKILL are left below as genuine failures: the CUDA
        # backend's abort() is exactly what this exists to catch, and an
        # OOM-kill is a real answer about this configuration's footprint.
        log.debug("[LOAD_PROBE] terminated externally — unproven, not recorded")
        return UNPROVEN_UNAVAILABLE, "probe terminated externally (unproven)"

    # rc 4/5 are honest Python-level failures; a negative rc is a signal
    # (SIGABRT is what the CUDA backend raises), which is the case this exists
    # for. Both are proof the configuration does not work here.
    _record(model_path, n_ctx, n_gpu_layers, n_batch, False, f"rc={rc} {tail}")
    log.debug("[LOAD_PROBE] ctx=%d layers=%d batch=%d FAILED rc=%d (%.1fs) %s",
              n_ctx, n_gpu_layers, n_batch, rc, elapsed, tail)
    return PROVEN_BAD, f"rc={rc} {tail}".strip()


def probe_config(model_path: str, n_ctx: int, n_gpu_layers: int, n_batch: int,
                 *, use_cache: bool = True,
                 timeout_s: Optional[float] = None) -> Tuple[bool, str]:
    """Boolean view of :func:`probe_verdict` — ``ok`` is "not proven bad".

    Kept because it is the honest answer to "did this fail?". Callers that are
    about to load an over-committed configuration want probe_verdict instead,
    so they can tell a timeout from a clean pass.
    """
    verdict, detail = probe_verdict(model_path, n_ctx, n_gpu_layers, n_batch,
                                    use_cache=use_cache, timeout_s=timeout_s)
    return verdict != PROVEN_BAD, detail
