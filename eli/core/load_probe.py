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
caller's context. The verdict is cached per (model, parameters, GPU identity) with
the free VRAM it was reached at, so a configuration is proven once rather than on
every startup, and is re-proven when free VRAM has since moved by more than the
configured headroom (another program took the card, or let it go).
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

# A probe blocks startup, so the budget is what an operator would sit through, not what is
# certain to finish. Past it the answer is "unproven" and startup carries on. Cost scales with
# model size and ctx, so the budget is derived from both. ELI_LOAD_PROBE_TIMEOUT overrides it.
_TIMEOUT_BASE_S = 30.0        # process spawn + import + backend init
_TIMEOUT_PER_GB_S = 10.0      # synchronous per-layer VRAM upload — only the VRAM-resident share
_TIMEOUT_PER_GB_DISK_S = 2.0  # cold mmap page-in from disk, the rest of a MoE model's file
_TIMEOUT_PER_1K_CTX_S = 2.0   # prefill, worst case with CPU-spilled layers
_TIMEOUT_FLOOR_S = 30.0
# The ceiling stops a startup probe blocking forever: three minutes at most, once per
# configuration (cached, timeouts remembered), only when the request already exceeds the measured
# fit, and the caller prints the real number first. A typical 2-5GB model settles well inside it.
_TIMEOUT_CEILING_S = 180.0
# A mixture-of-experts model's budget is scaled to its real (small) VRAM-bound share, not the
# full file at the VRAM-upload rate — that number is trustworthy enough to earn more room than
# the old always-pessimistic full-size estimate, which was already known wrong and got the same
# cap as everything else regardless of how wrong.
_TIMEOUT_MOE_CEILING_S = 240.0

# Verdicts older than this are re-proven — drivers, other GPU tenants and
# resident models all move. Override with ELI_LOAD_PROBE_TTL.
_DEFAULT_TTL_S = 7 * 24 * 3600.0

# A timeout is not a verdict, so it is not cached as one. It is still remembered
# briefly: without this, a configuration too slow to settle re-pays the FULL budget
# on every launch forever. Short enough that a machine which frees up gets retried.
_TIMEOUT_MEMO_TTL_S = 3600.0


def _probe_budget_sizes_gb(model_path: str) -> tuple:
    """(vram_bound_gb, total_gb) — what the timeout budget should actually scale on.

    _TIMEOUT_PER_GB_S was calibrated for the slow part of a cold load: synchronous, per-layer
    VRAM upload. A mixture-of-experts model under expert offload only pays that cost for the
    small resident share (attention/shared weights); the much larger expert share stays in RAM,
    a plain mmap page-in at disk speed, not VRAM-upload speed. Budgeting the full file at the
    VRAM rate — the previous behaviour — overshot so far past the 180s ceiling for a 24GB MoE
    model that a probe already fixed to test the right configuration (moe_expert_offload=True)
    still always looked "unproven": the estimate said ~294s were needed and the ceiling cut it
    at 180s regardless of what the probe itself was actually measuring.
    """
    try:
        total_gb = Path(model_path).stat().st_size / (1024 ** 3)
    except Exception:
        log.debug("load_probe: model size unreadable for timeout scaling", exc_info=True)
        return 0.0, 0.0
    vram_bound_gb = total_gb
    try:
        from eli.core import moe_offload as _moe_lp
        _plan = _moe_lp.plan_for_load(str(model_path), True)
        if _plan and _plan.get("resident_gb") is not None:
            vram_bound_gb = float(_plan["resident_gb"])
    except Exception:
        log.debug("[LOAD_PROBE] moe plan lookup failed for timeout scaling", exc_info=True)
    return vram_bound_gb, total_gb


def probe_timeout_for(model_path: str, n_ctx: int) -> float:
    """Seconds to allow this model at this context before calling it unproven.

    Public so the caller can tell the operator the real number instead of a
    constant that no longer matches what the probe will actually spend.
    """
    override = (os.environ.get("ELI_LOAD_PROBE_TIMEOUT", "") or "").strip()
    if override:
        try:
            return max(1.0, float(override))
        except ValueError:
            log.debug("ELI_LOAD_PROBE_TIMEOUT is not a number: %r", override)
    vram_bound_gb, total_gb = _probe_budget_sizes_gb(model_path)
    budget = _uncapped_budget(vram_bound_gb, total_gb, n_ctx)
    # A budget scaled to the real (MoE-aware) cost deserves a higher ceiling than the old
    # always-pessimistic full-size estimate did — that estimate was already known-wrong for MoE,
    # capping it at the same 180s as everything else just hid the wrongness instead of fixing it.
    ceiling = _TIMEOUT_CEILING_S if vram_bound_gb >= total_gb else _TIMEOUT_MOE_CEILING_S
    return float(min(ceiling, max(_TIMEOUT_FLOOR_S, budget)))


def _uncapped_budget(vram_bound_gb: float, total_gb: float, n_ctx: int) -> float:
    # The VRAM-upload rate already stands in for "read from disk + upload" for whatever IS VRAM-
    # bound (matches the old, single-term formula exactly when vram_bound_gb == total_gb, i.e. no
    # MoE plan). The separate, cheaper disk rate applies only to the REMAINDER — the expert share
    # that skips the VRAM step entirely — not the full file on top of the VRAM term.
    disk_only_gb = max(0.0, total_gb - vram_bound_gb)
    return (
        _TIMEOUT_BASE_S
        + vram_bound_gb * _TIMEOUT_PER_GB_S
        + disk_only_gb * _TIMEOUT_PER_GB_DISK_S
        + (max(0, int(n_ctx)) / 1000.0) * _TIMEOUT_PER_1K_CTX_S
    )


def budget_is_ceiling_cut(model_path: str, n_ctx: int) -> bool:
    """True when the probe's own estimate exceeds its ceiling, so it is expected to be cut off."""
    if (os.environ.get("ELI_LOAD_PROBE_TIMEOUT", "") or "").strip():
        return False
    vram_bound_gb, total_gb = _probe_budget_sizes_gb(model_path)
    if vram_bound_gb <= 0.0 and total_gb <= 0.0:
        return False
    ceiling = _TIMEOUT_CEILING_S if vram_bound_gb >= total_gb else _TIMEOUT_MOE_CEILING_S
    return _uncapped_budget(vram_bound_gb, total_gb, n_ctx) > ceiling


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
        # A probe failure is not a confirmed CPU-only machine. Both used to memoise as "cpu", so a
        # transient early-boot detection error mislabelled the cache identity for the whole session.
        # Return "cpu" for this call only and don't cache it, so the next call can detect the GPU.
        log.debug("load_probe: GPU identity unavailable", exc_info=True)
        return "cpu"
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


def _free_vram_mb() -> Optional[int]:
    try:
        from eli.core.hardware_profile import get_live_gpu_telemetry
        free = get_live_gpu_telemetry().get("free_mb")
        return int(free) if free is not None else None
    except Exception:
        return None


def _vram_moved(then: Any, now: Optional[int], *, up: bool) -> bool:
    """Whether free VRAM rose (up) or fell by more than the configured headroom since a verdict.
    A verdict reached while another program held the card says nothing about the card once it
    is free, and a pass reached on a free card says nothing once another program holds it."""
    if then is None or now is None:
        return False
    try:
        from eli.core.hardware_profile import vram_reserve_mb
        margin = int(vram_reserve_mb())
    except Exception:
        return False
    return (now - int(then) > margin) if up else (int(then) - now > margin)


def cached_verdict(model_path: str, n_ctx: int, n_gpu_layers: int,
                   n_batch: int, *, free_mb: Optional[int] = None) -> Optional[bool]:
    """A previously proven verdict for these parameters, or None. With free_mb, a pass reached
    with much more VRAM free, or a failure reached with much less, does not count."""
    ttl = float(os.environ.get("ELI_LOAD_PROBE_TTL", "") or _DEFAULT_TTL_S)
    entry = _load_cache().get(_key(model_path, n_ctx, n_gpu_layers, n_batch))
    if not isinstance(entry, dict):
        return None
    if time.time() - float(entry.get("ts", 0) or 0) > ttl:
        return None
    ok = entry.get("ok")
    if not isinstance(ok, bool):
        return None
    if _vram_moved(entry.get("free_mb"), free_mb, up=not ok):
        return None
    return ok


def _timeout_key(model_path: str, n_ctx: int, n_gpu_layers: int, n_batch: int) -> str:
    return "timeout:" + _key(model_path, n_ctx, n_gpu_layers, n_batch)


def _recently_timed_out(model_path: str, n_ctx: int, n_gpu_layers: int,
                        n_batch: int, *, free_mb: Optional[int] = None) -> bool:
    entry = _load_cache().get(_timeout_key(model_path, n_ctx, n_gpu_layers, n_batch))
    if not isinstance(entry, dict):
        return False
    if _vram_moved(entry.get("free_mb"), free_mb, up=True):
        return False                 # the card has freed up since: worth trying again
    # A timeout at a ceiling-cut budget repeats identically every launch; the key already
    # carries model size and GPU identity, so remember it for the full TTL.
    ttl = _DEFAULT_TTL_S if entry.get("ceiling_cut") else _TIMEOUT_MEMO_TTL_S
    return (time.time() - float(entry.get("ts", 0) or 0)) < ttl


def _record_timeout(model_path: str, n_ctx: int, n_gpu_layers: int,
                    n_batch: int, *, free_mb: Optional[int] = None) -> None:
    cache = _load_cache()
    cache[_timeout_key(model_path, n_ctx, n_gpu_layers, n_batch)] = {
        "ts": time.time(),
        "free_mb": free_mb,
        "ceiling_cut": bool(budget_is_ceiling_cut(model_path, n_ctx)),
        "model": str(model_path),
        "n_ctx": int(n_ctx),
        "n_gpu_layers": int(n_gpu_layers),
        "n_batch": int(n_batch),
        "gpu": _gpu_identity(),
    }
    _save_cache(cache)


def _record(model_path: str, n_ctx: int, n_gpu_layers: int, n_batch: int,
            ok: bool, detail: str = "", *, free_mb: Optional[int] = None) -> None:
    cache = _load_cache()
    cache[_key(model_path, n_ctx, n_gpu_layers, n_batch)] = {
        "ok": bool(ok),
        "ts": time.time(),
        "free_mb": free_mb,
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
import json, os, sys, time
_t0 = time.monotonic()
cfg = json.loads(sys.argv[1])
try:
    from llama_cpp import Llama
except Exception as e:
    print("IMPORT_FAIL:%s" % e, file=sys.stderr)
    raise SystemExit(3)
_moe_ctx = None
if cfg.get("moe_expert_offload"):
    try:
        from eli.core import moe_offload as _moe
        cfg["n_gpu_layers"] = _moe.full_offload_layers(cfg["n_gpu_layers"], cfg["model_path"])
        _moe_ctx = _moe.expert_offload_params()
        _moe_ctx.__enter__()
    except Exception:
        _moe_ctx = None
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
finally:
    if _moe_ctx is not None:
        try:
            _moe_ctx.__exit__(None, None, None)
        except Exception:
            pass
print("LOADED %.1f" % (time.monotonic() - _t0), flush=True)
# Drive a real decode: loading alone proves nothing (the abort happened with the model resident and
# the context created). The compute buffer for a large prompt isn't allocated until generation, so
# push a prompt of the size the caller will really use.
# In chunks, so a check that runs out of time says how far it got and how fast. Then one decode step on
# top of the full context: generation allocates nothing the prompt did not, and its CPU-side layers are
# what slows ~10x when other programs keep the cores busy (measured: 31 tokens 1.9 s idle, 19 s loaded).
try:
    toks = llm.tokenize(("word " * int(cfg["probe_tokens"])).encode("utf-8"))
    step = max(1, int(cfg["n_batch"])) * 8
    for i in range(0, len(toks), step):
        llm.eval(toks[i:i + step])
        print("EVAL %d %d %.1f" % (min(i + step, len(toks)), len(toks), time.monotonic() - _t0), flush=True)
    llm.eval(toks[-1:])
except Exception as e:
    print("DECODE_FAIL:%s" % e, file=sys.stderr)
    raise SystemExit(5)
print("PROBE_OK %.1f" % (time.monotonic() - _t0), flush=True)
sys.stderr.flush()
# A throwaway process: nothing to tidy, and a slow teardown must not cost the verdict.
os._exit(0)
'''


# Verdicts. The caller needs the difference between "proved fine" and "could not
# prove anything", because it is deciding whether to load a configuration that
# measurement already says does not fit.
PROVEN_OK = "ok"            # ran, survived a real decode
PROVEN_BAD = "bad"          # ran, failed (this is what the CUDA abort looks like)
UNPROVEN_TIMEOUT = "timeout"      # ran, did not finish in the budget
UNPROVEN_UNAVAILABLE = "unavailable"  # could not run at all — no information
SKIPPED = "skipped"         # nothing to prove (cpu-only, disabled)


def _stage_reached(stdout: str, probe_tokens: int) -> str:
    """How far the child got, from the lines it printed as it went."""
    marks, done = {}, None
    for line in str(stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in ("LOADED", "PROBE_OK"):
            marks[parts[0]] = parts[1]
        elif len(parts) == 4 and parts[0] == "EVAL":
            try:
                done = (int(parts[1]), int(parts[2]), float(parts[3]))
            except ValueError:
                continue  # a progress line cut off by the timeout
    if "PROBE_OK" in marks:
        return f"loaded and ran the {probe_tokens}-token test prompt in {marks['PROBE_OK']}s"
    if "LOADED" in marks:
        loaded = marks["LOADED"]
        if done:
            n, total, at = done
            try:
                rate = n / max(0.1, at - float(loaded))
            except ValueError:
                rate = 0.0
            return (f"loaded in {loaded}s; the test prompt was at {n}/{total} tokens after {at:.0f}s "
                    f"({rate:.0f} tokens/s)")
        return f"loaded in {loaded}s; the {probe_tokens}-token test prompt had not finished its first chunk"
    return "the model had not finished loading"


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
    free_now = _free_vram_mb() if n_gpu_layers > 0 else None

    if use_cache:
        cached = cached_verdict(model_path, n_ctx, n_gpu_layers, n_batch, free_mb=free_now)
        if cached is not None:
            return (PROVEN_OK if cached else PROVEN_BAD), "cached verdict"

    # CPU-only configurations cannot hit the CUDA abort this exists to catch,
    # and a probe would cost a full cold load for nothing.
    if n_gpu_layers <= 0:
        return SKIPPED, "cpu-only: no GPU allocation to prove"

    # A mixture-of-experts model offloads with experts kept in RAM regardless of layer count — a
    # different, much lighter VRAM footprint than a naive per-layer split would suggest. The
    # caller (gguf_inference.py / the GUI loader) now sizes n_gpu_layers from that real footprint
    # itself (moe_resident_gb-aware smart-fit), so n_gpu_layers here already IS the real candidate
    # — probe it verbatim. Only the expert-offload FLAG needs setting, so the probe subprocess
    # applies the same tensor-buffer-type override the real load will.
    probe_gpu_layers = n_gpu_layers
    moe_expert_offload = False
    try:
        from eli.core import moe_offload as _moe_lp
        _moe_plan = _moe_lp.plan_for_load(str(model_path), True)
        if _moe_plan and int(_moe_plan.get("layers") or 0) > 0:
            moe_expert_offload = True
    except Exception:
        log.debug("[LOAD_PROBE] moe plan lookup failed", exc_info=True)

    # Probe sizes derive from the caller's parameters, no magic numbers. The prompt has to be the
    # size ELI will really send: a cheaper probe passed startups that later aborted at 5189 tokens,
    # because llama.cpp's peak allocation depends on prompt length. The timeout above bounds the cost.
    probe_tokens = max(256, int(n_ctx * 0.45))

    timeout = float(timeout_s if timeout_s is not None
                    else probe_timeout_for(model_path, n_ctx))

    if use_cache and _recently_timed_out(model_path, n_ctx, n_gpu_layers, n_batch, free_mb=free_now):
        return (UNPROVEN_TIMEOUT,
                "probe timed out recently; not re-paying the budget this launch")
    payload = json.dumps({
        "model_path": str(model_path),
        "n_ctx": n_ctx,
        "n_gpu_layers": probe_gpu_layers,
        "n_batch": n_batch,
        "moe_expert_offload": moe_expert_offload,
        "probe_tokens": probe_tokens,
    })

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _CHILD, payload],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as _late:
        seen = _late.stdout or ""
        seen = seen.decode("utf-8", "replace") if isinstance(seen, bytes) else str(seen)
        if "PROBE_OK" in seen:
            _record(model_path, n_ctx, n_gpu_layers, n_batch, True, "ok", free_mb=free_now)
            log.debug("[LOAD_PROBE] passed; the probe process did not exit inside %.0fs", timeout)
            return PROVEN_OK, f"verified ({_stage_reached(seen, probe_tokens)})"
        # Slow, not proven broken. Do not override the operator on a timeout, and do
        # not cache a VERDICT that was never reached — only the fact that it timed
        # out, briefly, so the next launch does not re-pay the same budget.
        _record_timeout(model_path, n_ctx, n_gpu_layers, n_batch, free_mb=free_now)
        stage = _stage_reached(seen, probe_tokens)
        log.debug("[LOAD_PROBE] timed out after %.0fs — treating as unproven; %s", timeout, stage)
        return UNPROVEN_TIMEOUT, f"probe timed out after {timeout:.0f}s (unproven): {stage}"
    except Exception as e:
        log.debug("[LOAD_PROBE] could not run: %s", e)
        return UNPROVEN_UNAVAILABLE, f"probe unavailable: {e}"

    elapsed = time.perf_counter() - t0
    rc = int(proc.returncode or 0)
    # Prefer the child's own marker line. LlamaModel.__del__ raises "'LlamaModel' object has no
    # attribute 'sampler'" after a constructor failure, so the last stderr line reported the
    # destructor's noise instead of "Failed to load model from file".
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
        _record(model_path, n_ctx, n_gpu_layers, n_batch, True, "ok", free_mb=free_now)
        log.debug("[LOAD_PROBE] ctx=%d layers=%d batch=%d verified in %.1fs",
                  n_ctx, n_gpu_layers, n_batch, elapsed)
        return PROVEN_OK, f"verified in {elapsed:.1f}s"

    if rc == 3:
        # llama_cpp missing in the child — the check could not run.
        return UNPROVEN_UNAVAILABLE, "llama_cpp unavailable in probe (unproven)"

    if rc == -15:
        # SIGTERM means something outside asked the probe to stop, which says nothing about the
        # configuration, so it isn't recorded as a verdict. SIGABRT/SIGSEGV/SIGKILL stay genuine failures:
        # the CUDA abort() is what this exists to catch, and an OOM-kill is a real answer.
        log.debug("[LOAD_PROBE] terminated externally — unproven, not recorded")
        return UNPROVEN_UNAVAILABLE, "probe terminated externally (unproven)"

    # rc 4/5 are honest Python-level failures; a negative rc is a signal
    # (SIGABRT is what the CUDA backend raises), which is the case this exists
    # for. Both are proof the configuration does not work here.
    _record(model_path, n_ctx, n_gpu_layers, n_batch, False, f"rc={rc} {tail}", free_mb=free_now)
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
