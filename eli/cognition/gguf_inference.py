"""
GGUF inference for ELI — model-agnostic.

Detects the loaded model's family from its filename and applies the correct chat
template (Mistral/Mixtral [INST], Llama-3 headers, Qwen/ChatML, etc.). No model
name, size, or path is assumed; everything resolves from config/env.

(no hardcoded paths, no forced parameter lowering):
- Adds optional KV-cache quantization via env:
    ELI_GGUF_CACHE_TYPE_K (e.g. q4_0, q8_0)
    ELI_GGUF_CACHE_TYPE_V (e.g. q4_0, q8_0)
  This is the main way to keep large n_ctx on big models without llama_context allocation failure.

- Adds optional runtime knobs (env) without changing your defaults:
    ELI_GGUF_THREADS
    ELI_GGUF_USE_MMAP
    ELI_GGUF_USE_MLOCK
    ELI_GGUF_VERBOSE

- Adds compatibility fallback: if llama-cpp-python doesn't accept the extra kwargs,
  it retries without them (keeping your model + n_ctx unchanged).
"""

from __future__ import annotations


def _eli_normalize_prompt(prompt=None, messages=None, system=None, **kwargs):
    if prompt is not None:
        return (system or ""), str(prompt)

    fallback = (
        kwargs.get("user_message")
        or kwargs.get("message")
        or kwargs.get("text")
        or kwargs.get("query")
        or kwargs.get("content")
        or ""
    )

    if not messages:
        return (system or ""), str(fallback)

    sys_text = system or ""
    parts = []

    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "")).strip().lower()
        content = str(m.get("content", "")).strip()
        if not content:
            continue
        if role == "system" and not sys_text:
            sys_text = content
        elif role == "user":
            parts.append(content)
        elif role == "assistant":
            parts.append(f"ELI said previously: {content}")

    prompt_text = "\n".join(parts).strip()
    if not prompt_text:
        prompt_text = str(fallback)

    return sys_text, prompt_text


import os
import json
import re
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, Generator, Union

from llama_cpp import Llama, LlamaGrammar


def _env_int(name: str, default: Optional[int] = None) -> Optional[int]:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except Exception:
        log.debug(f"[GGUF] Warning: {name}={v!r} is not an int; ignoring")
        return default


def _env_bool(name: str, default: Optional[bool] = None) -> Optional[bool]:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    v = v.strip().lower()
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off"):
        return False
    log.debug(f"[GGUF] Warning: {name}={v!r} is not a bool; ignoring")
    return default

def _load_runtime_settings() -> Dict[str, Any]:
    try:
        from eli.core import runtime_settings
        data = runtime_settings.load_settings()
        return dict(data or {})
    except Exception:
        return {}


def _runtime_value(settings: Dict[str, Any], *keys: str, default=None):
    for key in keys:
        if key in settings and settings.get(key) not in (None, ""):
            return settings.get(key)
    return default


def _as_int(value, fallback):
    try:
        return int(value)
    except Exception:
        return int(fallback)


_last_error: Optional[str] = None
_last_params: Dict[str, Any] = {}

def get_model_path() -> Optional[Path]:
    # Strongest override: explicit file path. If explicitly set and missing, do not silently fall back.
    env_path = os.environ.get("ELI_GGUF_MODEL_PATH")
    if env_path:
        p = Path(env_path).expanduser()
        if p.exists():
            return p
        log.debug(f"[GGUF] Warning: ELI_GGUF_MODEL_PATH={p} does not exist")
        return None

    if os.getenv("PYTEST_CURRENT_TEST"):
        return None

    settings = _load_runtime_settings()
    provider = str(settings.get("provider", "") or "").strip().lower()
    if provider != "ollama":
        for key in ("model_path", "custom_model_path", "bundled_model_path"):
            path_value = settings.get(key)
            if path_value:
                p = Path(str(path_value)).expanduser()
                if p.exists():
                    return p

    # Next: (models dir, filename) pair
    model_name = os.environ.get("ELI_GGUF_MODEL")
    models_dir = os.environ.get("ELI_MODELS_DIR")
    if model_name and models_dir:
        cand = (Path(models_dir).expanduser().resolve() / model_name)
        if cand.exists():
            return cand

    # Next: PATHS.model (portable dirs / platformdirs)
    try:
        from eli.core.paths import PATHS
        cand = getattr(PATHS, "model", None)
        cand = cand() if callable(cand) else cand
        if cand and Path(cand).exists():
            return Path(cand)
    except Exception:
        pass

    from eli.core import config
    path = config.get("gguf_model_path")
    if path:
        p = Path(path).expanduser()
        if p.exists():
            return p

    return None


def _is_mistral_model(model_path: Optional[Path]) -> bool:
    """Pure Mistral/Mixtral models use [INST] <<SYS>> format."""
    if model_path is None:
        return False
    name = str(model_path).lower()
    # OpenHermes, Hermes, and other ChatML fine-tunes built on Mistral base
    # use ChatML format despite containing "mistral" in their filename.
    # Exclude them here so _is_chatml_model catches them first.
    _chatml_override = ("openhermes", "hermes", "dolphin", "zephyr", "neural")
    if any(x in name for x in _chatml_override):
        return False
    return "mistral" in name or "mixtral" in name


def _is_chatml_model(model_path: Optional[Path]) -> bool:
    """
    Models fine-tuned with the ChatML prompt format:
    Qwen, DeepSeek, OpenHermes, Hermes, Dolphin, Zephyr, StableCode, etc.
    """
    if model_path is None:
        return False
    name = str(model_path).lower()
    _chatml_names = (
        "qwen", "deepseek", "openhermes", "hermes", "dolphin",
        "zephyr", "stable-code", "starcoder", "neural", "chatml",
    )
    return any(x in name for x in _chatml_names)



def _is_llama_model(model_path: Optional[Path]) -> bool:
    """Llama-3 models use header-based format."""
    if model_path is None:
        return False
    name = str(model_path).lower()
    return (
        "llama-3" in name or "llama3" in name
        or "meta-llama-3" in name or "llama_3" in name
    )


def _is_thinking_model(model_path: Optional[Path] = None) -> bool:
    """Heuristic: does the ACTUALLY-LOADED model emit a <think>…</think> reasoning block
    by default? Name-based (Qwen3 family, DeepSeek-R1 / R1-distill, QwQ). Extend as new
    reasoning families appear. Used to disable thinking on utility calls.

    Reads the LOADED model identity first — the live runtime override published when a
    model is loaded — NOT settings/get_model_path(). The GUI can load one model (e.g. a
    Qwen3 A3B) while settings.json still points at another (the 7B); using settings
    misdetected the reasoning model as non-reasoning, so the no-think prefill never fired
    and the A3B thought through every routing/summary/code budget → empty → fallback."""
    if model_path is not None:
        name = str(model_path).lower()
    else:
        _ov = globals().get("_live_runtime_override") or globals().get("_live_runtime_params") or {}
        name = str(_ov.get("model_name") or _ov.get("model_path") or "").lower()
        if not name:
            name = str(get_model_path() or "").lower()
    return any(k in name for k in ("qwen3", "deepseek-r1", "r1-distill", "qwq", "-r1-"))


def _no_think_prefill(*, structured: bool, max_tokens) -> str:
    """Return an assistant-turn PREFILL that forces a reasoning model to SKIP its
    <think> block on UTILITY calls, so it doesn't burn a small budget thinking instead
    of producing the structured/short output ELI needs (the bug where the A3B routed
    everything to fallback.chat and failed session summaries because <think> ate the
    90/420-token budget). Prefilling a CLOSED empty think is reliable across reasoning
    families — the /no_think soft-switch is ignored by some Qwen3 quants.

    Disabled for: structured/JSON calls (always) and small-budget chat (< 1024 tokens →
    judge / summary / quick utility). The MAIN answer call (large budget) keeps thinking
    unless ELI_MODEL_THINK=0. '' (no-op) for non-reasoning models or when thinking is
    wanted."""
    if not _is_thinking_model():
        return ""
    try:
        _small = 0 < int(max_tokens or 0) < 1024
    except Exception:
        _small = False
    # UTILITY calls (structured/JSON, OR small-budget chat: routing, reflection, insight,
    # news synthesis, summary, judge) NEVER think — they have no budget for it and need the
    # short/structured output. This holds REGARDLESS of the Think toggle (the earlier bug:
    # ELI_MODEL_THINK=1 made these think and empty). The toggle only governs the MAIN
    # answer call (large budget): think unless explicitly OFF.
    if structured or _small:
        disable = True
    else:
        _env = os.environ.get("ELI_MODEL_THINK", "").strip().lower()
        disable = _env in ("0", "false", "no", "off")
    return "<think>\n\n</think>\n\n" if disable else ""


# ── Future-proof template detection: read the model's OWN embedded template ───
# A GGUF carries its chat template in metadata (`tokenizer.chat_template`). Using
# it means ANY model — current or future — routes to the right prompt format
# regardless of its filename. We content-sniff the template for the major
# families (chatml/llama3/mistral/gemma/phi); a genuinely novel template falls
# back to the filename heuristics, then the generic format.
_TEMPLATE_FAMILY_CACHE: dict = {}


def _gguf_model_metadata() -> dict:
    """Embedded metadata of the loaded model (`_llm.metadata`); {} if unavailable."""
    try:
        llm = globals().get("_llm")
        md = getattr(llm, "metadata", None) if llm is not None else None
        return md if isinstance(md, dict) else {}
    except Exception:
        return {}


def _gguf_template_family() -> Optional[str]:
    """Family from the model's EMBEDDED chat template, or None to fall back."""
    md = _gguf_model_metadata()
    tmpl = str(md.get("tokenizer.chat_template") or "")
    if not tmpl:
        return None
    key = tmpl[:64]
    cached = _TEMPLATE_FAMILY_CACHE.get(key)
    if cached is not None:
        return cached or None
    if "<|im_start|>" in tmpl:
        fam = "chatml"
    elif "<|start_header_id|>" in tmpl or "<|eot_id|>" in tmpl:
        fam = "llama"
    elif "<start_of_turn>" in tmpl:
        fam = "gemma"
    elif "[INST]" in tmpl:
        fam = "mistral"
    elif "<|assistant|>" in tmpl or "<|user|>" in tmpl:
        fam = "phi"
    else:
        fam = ""  # unknown embedded template → fall back
    _TEMPLATE_FAMILY_CACHE[key] = fam
    return fam or None


def _gguf_param_count() -> int:
    """Parameter count from embedded metadata, else 0."""
    md = _gguf_model_metadata()
    for k in ("general.parameter_count", "general.size_label"):
        v = md.get(k)
        if v:
            try:
                return int(str(v).split()[0].replace(",", ""))
            except Exception:
                continue
    return 0
def _canonical_eli_persona() -> str:
    try:
        from eli.cognition.persona import get_persona as _get_persona
        val = (_get_persona() or "").strip()
        if val:
            return val
    except Exception:
        pass

    try:
        from eli.core import config
        val = (config.get_persona() or "").strip()
        if val:
            return val
    except Exception:
        pass

    return "You are ELI, a local reasoning and automation assistant. Be direct, accurate, grounded, privacy-preserving, and useful."

def _strip_think_text(t: str) -> str:
    """Remove a <think>…</think> reasoning block (or an unterminated one) from text.
    Reasoning models (Qwen3 / Qwen3.x-A3B, DeepSeek-R1, …) emit a PRIVATE
    chain-of-thought before the answer that must never surface. Keeps whatever
    follows the last </think>; drops a never-closed think outright. Model-agnostic —
    a no-op for models that don't think."""
    if "<think" not in (t or "").lower():
        return t
    t = re.sub(r"(?is)<think\s*>.*?</think\s*>", "", t)
    if "</think>" in t.lower():
        t = re.split(r"(?i)</think\s*>", t)[-1]
    elif "<think" in t.lower():
        t = re.split(r"(?i)<think\s*>", t)[0]
    return re.sub(r"(?i)</?think\s*>", "", t).strip()


def _clean_eli_output(text: str) -> str:
    t = _strip_think_text(str(text or ""))
    # Strip Mistral prompt-echo: model sometimes echoes [INST]...[/INST] before answering
    # Keep only content AFTER the last [/INST] marker if present
    if "[/INST]" in t:
        t = t.split("[/INST]")[-1]
    if "<|im_end|>" in t:
        parts = t.split("<|im_end|>")
        # Take the last non-empty part
        t = next((p for p in reversed(parts) if p.strip()), t)
    t = t.replace("[INST]", "").replace("[/INST]", "").replace("<s>", "").replace("</s>", "")
    t = t.replace("Assistant:", "ELI:").replace("assistant:", "ELI:").replace("AI:", "ELI:")
    t = t.replace("<|im_start|>", "").replace("<|im_end|>", "").replace("assistant\n", "")
    t = t.strip()
    t = re.sub(r"^\s*ELI:\s*", "", t)
    # Strip canned completion-style prefixes the model outputs in prompt-continuation mode
    t = re.sub(r"^\s*Short\s+answer\s*:\s*", "", t, flags=re.I)
    t = re.sub(r"^\s*(?:Answer|Response|Reply)\s*:\s*", "", t, flags=re.I)
    t = t.strip()

    bad_heads = (
        "i'm an ai",
        "i am an ai",
        "as an ai",
        "i'm just an ai",
        "i am just an ai",
        "i don't have a head",
        "i do not have a head",
        "i don't have personal memories",
        "i do not have personal memories",
        "i can't retain information",
        "i cannot retain information",
        "i don't have a memory like humans",
        "i do not have a memory like humans",
        "i don't store information between",
        "i do not store information between",
        "unlike humans, i don't",
        "as a language model",
        "as an llm",
        "as a large language model",
    )
    low = t.lower().strip()
    if any(low.startswith(p) for p in bad_heads):
        # Strip the offending preamble and return what's left, or a retry hint
        log.debug(f"[GGUF][CLEAN] Persona drift stripped: {t[:80]!r}")
        # Try to salvage content after the first sentence
        rest = re.sub(r"^[^.!?]*[.!?]\s*", "", t, count=1).strip()
        if len(rest) >= 2:
            return rest
        return t  # return full original — empty responses are worse than imperfect ones
    # Strip model meta-commentary appended after main response
    t = re.sub(r'\s*\(Note:[^)]{0,400}\)', '', t, flags=re.I).strip()
    t = re.sub(r'\s*\[Note:[^\]]{0,400}\]', '', t, flags=re.I).strip()
    t = re.sub(r'\s*\(Note:.*$', '', t, flags=re.I | re.DOTALL).strip()

    if not t.strip():
        log.debug(f"[GGUF][CLEAN] Empty after cleaning, returning raw fallback")
        # Strip think + meta-commentary from the fallback too — NEVER surface raw
        # chain-of-thought just because the cleaned text came out empty (e.g. the
        # model spent its whole budget thinking).
        raw_fallback = _strip_think_text(str(text or "")).strip()
        raw_fallback = re.sub(r'\s*\(Note:.*$', '', raw_fallback, flags=re.I | re.DOTALL).strip()
        return raw_fallback if raw_fallback else ''
    return t.strip()

def _strip_think_stream(chunks):
    """Suppress a leading <think>…</think> reasoning block from a token stream
    (Qwen3 / DeepSeek-R1 etc.). Engages ONLY when the output begins with <think>,
    so it adds no latency and is a pure pass-through for non-reasoning models."""
    buf = ""
    mode = "detect"  # detect → suppress → pass  (or detect → pass)
    for chunk in chunks:
        raw = chunk.get("response", "") if isinstance(chunk, dict) else str(chunk or "")
        if not raw:
            continue
        if mode == "pass":
            yield {"response": raw}
            continue
        buf += raw
        low = buf.lstrip().lower()
        if mode == "suppress":
            if "</think>" in low:
                after = re.split(r"(?i)</think\s*>", buf, maxsplit=1)[-1]
                buf, mode = "", "pass"
                if after.strip():
                    yield {"response": after}
            continue
        # detect: is this a thinking model emitting <think> first?
        if low.startswith("<think"):
            mode = "suppress"
            if "</think>" in low:
                after = re.split(r"(?i)</think\s*>", buf, maxsplit=1)[-1]
                buf, mode = "", "pass"
                if after.strip():
                    yield {"response": after}
            continue
        # still undecided (leading whitespace, or a partial prefix of "<think")?
        # keep buffering up to a small cap; otherwise it's not a thinker → flush.
        if (low == "" or "<think".startswith(low)) and len(buf) < 12:
            continue
        mode = "pass"
        yield {"response": buf}
        buf = ""
    if buf and mode != "suppress":
        yield {"response": buf}


def _stream_clean_chunks(chunks):
    """True streaming cleaner; hold only obvious role prefixes."""
    head_buffer = ""
    started = False
    max_head = 80
    possible_prefixes = {
        "", "e", "el", "eli", "eli:",
        "a", "as", "ass", "assi", "assis", "assist", "assista",
        "assistan", "assistant", "assistant:",
        "ai", "ai:",
    }

    for chunk in chunks:
        raw = chunk.get("response", "") if isinstance(chunk, dict) else str(chunk or "")
        if not raw:
            continue
        if started:
            yield {"response": raw}
            continue
        head_buffer += raw
        log.debug(f"[GGUF][RAW_HEAD] {head_buffer[:400]!r}")
        stripped = head_buffer.strip().lower()
        if stripped in possible_prefixes and len(head_buffer) < max_head:
            continue
        cleaned = _clean_eli_output(head_buffer)
        if cleaned:
            started = True
            yield {"response": cleaned}
            continue
        if len(head_buffer) >= max_head:
            started = True
            fallback = re.sub(r"^\s*(?:ELI|Assistant|AI)\s*:\s*", "", head_buffer, flags=re.I).strip()
            if fallback:
                yield {"response": fallback}

    if not started and head_buffer:
        cleaned = _clean_eli_output(head_buffer)
        if cleaned:
            yield {"response": cleaned}


_llm: Optional[Llama] = None
_live_runtime_override: Optional[Dict[str, Any]] = None
_load_failed: bool = False  # sentinel: don't retry after a confirmed failure
try:
    from eli.runtime.native_locks import LLAMA_CPP_NATIVE_LOCK as _LLM_CALL_LOCK
except Exception:
    _LLM_CALL_LOCK = threading.RLock()

# ── Foreground-priority preemption ────────────────────────────────────────────
# All generation serialises on _LLM_CALL_LOCK. On a slow/CPU-offloaded model a
# background daemon generation (news synthesis, insight, morning report) can hold
# that lock for minutes — and a user's foreground turn then queues behind it (the
# logs showed a memory agent stalled 381s behind a 447s background news synth).
#
# Fix: a foreground generation SETS _FG_PRIORITY before it blocks on the lock;
# any in-flight BACKGROUND generation carries a llama.cpp stopping_criteria that
# returns True the moment _FG_PRIORITY is set, so it yields the lock at the next
# token and the foreground turn jumps the queue. Background work is marked per
# THREAD (set_background_inference) — the proactive daemon marks its loop thread,
# so every generation it triggers is abortable regardless of the call path.
# Kill switch: ELI_FG_PREEMPT=0.
_FG_PRIORITY = threading.Event()
# Set at shutdown to abort EVERY in-flight generation at the next token. A background
# self-improvement/codegen call can sit in a single native llm() call for 10+ minutes;
# the OS can't kill a thread mid-native-call, so shutdown's unload_model() (which needs
# the shared lock) blocked for 20-30 min. This cooperative abort lets any in-flight call
# yield at the next token so teardown proceeds immediately.
_SHUTDOWN = threading.Event()
_bg_tls = threading.local()


def signal_shutdown() -> None:
    """Abort ALL in-flight generations at the next token (foreground and background).
    Idempotent; called first thing in engine shutdown."""
    _SHUTDOWN.set()


def clear_shutdown() -> None:
    _SHUTDOWN.clear()


def is_shutting_down() -> bool:
    return _SHUTDOWN.is_set()


def set_background_inference(flag: bool) -> None:
    """Mark the CURRENT thread's generations as background (daemon) work — they
    install a cooperative abort so a foreground turn can preempt them."""
    _bg_tls.background = bool(flag)


def is_background_inference() -> bool:
    return bool(getattr(_bg_tls, "background", False))


def _fg_preempt_enabled() -> bool:
    return os.environ.get("ELI_FG_PREEMPT", "1").strip().lower() not in ("0", "false", "no", "off")


def _should_abort_generation(background: bool) -> bool:
    """True when an in-flight generation should yield at the next token: shutdown is
    signalled (aborts ANY call) or — for BACKGROUND calls with preemption enabled — a
    foreground turn is waiting on the shared lock."""
    if _SHUTDOWN.is_set():
        return True
    return bool(background) and _fg_preempt_enabled() and _FG_PRIORITY.is_set()


def _make_stopping_criteria(background: bool):
    """Cooperative abort installed on EVERY generation (see _should_abort_generation).
    Returns None only when llama_cpp is unavailable."""
    try:
        from llama_cpp import StoppingCriteriaList
    except Exception:
        return None

    def _crit(input_ids, logits) -> bool:
        return _should_abort_generation(background)

    return StoppingCriteriaList([_crit])


def load_model(force_reload: bool = False):
    global _llm

    import os
    import json as _json
    import time as _time
    from pathlib import Path as _Path
    from llama_cpp import Llama
    from llama_cpp import llama_cpp as _llama_native
    from eli.core import config
    from eli.core.paths import get_paths as _gp

    if _llm is not None and not force_reload:
        return _llm

    if force_reload:
        _llm = None

    settings = _load_runtime_settings()
    model_path = get_model_path()
    if not model_path:
        raise FileNotFoundError("No GGUF model path configured")

    model_path = _Path(model_path).expanduser().resolve()
    if not model_path.exists():
        raise FileNotFoundError(f"GGUF model not found: {model_path}")

    n_ctx = _env_int("ELI_GGUF_N_CTX", None)
    if n_ctx is None:
        n_ctx = _as_int(_runtime_value(settings, "n_ctx", "context_size"), config.get_gguf_n_ctx())

    # Co-resident vision: load the small fast model FIRST (reserving its VRAM).
    # The text model is then sized DYNAMICALLY to the VRAM left (see smart-fit
    # below) — no static ctx cap. Best-effort — if the fast model can't load,
    # we fall through to full context (no harm to boot).
    _co_resident_active = False
    if bool(_runtime_value(settings, "vision_coresident", default=False)):
        try:
            from eli.perception import vision as _eli_vision
            _rok, _rreason = _eli_vision.load_resident_fast_model()
            _co_resident_active = bool(_rok)
            if not _rok:
                log.debug(f"[GGUF] co-resident vision: fast model not loaded ({_rreason}); full ctx kept")
        except Exception as _co_err:
            log.debug(f"[GGUF] co-resident vision setup skipped: {_co_err}")

    n_gpu_layers = _env_int("ELI_GGUF_N_GPU_LAYERS", None)
    if n_gpu_layers is None:
        n_gpu_layers = _as_int(_runtime_value(settings, "gpu_layers", "n_gpu_layers"), config.get_gguf_n_gpu_layers())

    n_batch = _env_int("ELI_GGUF_N_BATCH", None)
    if n_batch is None:
        n_batch = _as_int(_runtime_value(settings, "batch_size", "n_batch"), config.get_gguf_n_batch())

    n_threads = _env_int("ELI_GGUF_THREADS", None)
    if n_threads is None:
        n_threads = _as_int(_runtime_value(settings, "cpu_threads", "n_threads"), os.cpu_count() or 4)

    # Co-resident vision → size the text model DYNAMICALLY to the VRAM left,
    # reducing GPU layers → batch → ctx (ctx last). No hardcoded cap; ctx ceiling
    # is the model's native train length × the user's fraction. Per-model,
    # per-machine. Skips cleanly if no GPU / no model path.
    if _co_resident_active:
        try:
            from eli.core.startup_hardware_optimizer import (
                detect_nvidia_gpus as _sf_dng, select_gpu as _sf_sg,
                train_ctx_for_model as _sf_tc,
            )
            from eli.core.hardware_profile import smart_fit_config as _sf_fit
            _sf_gpu = _sf_sg(_sf_dng())
            _mp = _runtime_value(settings, "model_path", "model") or ""
            if _sf_gpu and _sf_gpu.free_mb > 0 and _mp and os.path.exists(str(_mp)):
                _mgb = os.path.getsize(str(_mp)) / (1024 ** 3)
                _frac = float(os.environ.get("ELI_CTX_FRACTION", "0.9") or "0.9")
                _res = int(os.environ.get("ELI_VRAM_RESERVE_MB", "700") or "700")
                _kvq = bool(_sf_gpu.total_mb and _sf_gpu.total_mb < 12000)
                _want = max(2048, (int(int(_sf_tc(str(_mp))) * _frac) // 2048) * 2048)
                _fc, _fl, _fb = _sf_fit(
                    _mgb, _sf_gpu.free_mb, user_ctx=min(int(n_ctx), _want),
                    user_batch=int(n_batch), reserve_mb=_res, kv_quantized=_kvq,
                )
                log.debug(f"[GGUF] co-resident smart-fit: ctx {n_ctx}->{_fc} "
                          f"layers {n_gpu_layers}->{_fl} batch {n_batch}->{_fb} "
                          f"(free={_sf_gpu.free_mb}MB reserve={_res})")
                n_ctx, n_gpu_layers, n_batch = _fc, _fl, _fb
        except Exception as _sf_err:
            log.debug(f"[GGUF] co-resident smart-fit skipped: {_sf_err}")

    def _boolish(v, default=False):
        if v is None or v == "":
            return default
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("1", "true", "yes", "on")

    use_mmap = _runtime_value(settings, "use_mmap", default=True)
    use_mlock = _runtime_value(settings, "use_mlock", default=False)
    cache_k = _runtime_value(settings, "cache_type_k", "type_k", default=None)
    cache_v = _runtime_value(settings, "cache_type_v", "type_v", default=None)

    requested_n_gpu_layers = int(n_gpu_layers)
    gpu_offload_supported = None
    try:
        _supports_fn = getattr(_llama_native, "llama_supports_gpu_offload", None)
        if callable(_supports_fn):
            gpu_offload_supported = bool(_supports_fn())
    except Exception:
        gpu_offload_supported = None

    effective_n_gpu_layers = int(n_gpu_layers)
    if requested_n_gpu_layers > 0 and gpu_offload_supported is False:
        log.debug(
            "[GGUF][GPU] GPU offload unsupported on this runtime "
            "(driver/CUDA/backend unavailable). Forcing CPU mode.",
        )
        effective_n_gpu_layers = 0

    kwargs = {
        "model_path": str(model_path),
        "n_ctx": int(n_ctx),
        "n_threads": int(n_threads),
        "n_gpu_layers": int(effective_n_gpu_layers),
        "n_batch": int(n_batch),
        "verbose": False,
    }

    kwargs["use_mmap"] = _boolish(use_mmap, True)
    kwargs["use_mlock"] = _boolish(use_mlock, False)

    if cache_k:
        kwargs["cache_type_k"] = cache_k
    if cache_v:
        kwargs["cache_type_v"] = cache_v

    log.debug(
        "[GGUF] Params: "
        f"ctx={n_ctx}, gpu_layers={effective_n_gpu_layers}, batch={n_batch}, threads={n_threads} "
        f"(requested_gpu_layers={requested_n_gpu_layers}, gpu_offload_supported={gpu_offload_supported})"
    )

    try:
        _llm = Llama(**kwargs)
    except TypeError as e:
        _msg = str(e)
        if any(tok in _msg for tok in ("cache_type_k", "cache_type_v", "type_k", "type_v")):
            kwargs.pop("cache_type_k", None)
            kwargs.pop("cache_type_v", None)
            _llm = Llama(**kwargs)
        else:
            raise

    globals()["_live_runtime_params"] = {
        "provider": "gguf",
        "model_path": str(model_path),
        "model_name": model_path.name,
        "n_ctx": int(n_ctx),
        "n_gpu_layers": int(effective_n_gpu_layers),
        "n_threads": int(n_threads),
        "n_batch": int(n_batch),
        "requested_n_gpu_layers": int(requested_n_gpu_layers),
        "gpu_offload_supported": gpu_offload_supported,
        "load_mode": "GPU" if int(effective_n_gpu_layers) > 0 else "CPU",
        "loaded": True,
        "pid": os.getpid(),
        "ts": _time.time(),
    }

    try:
        snap_path = _Path(_gp().artifacts_dir) / "runtime_snapshot.json"
        snap_path.write_text(_json.dumps(globals()["_live_runtime_params"], indent=2), encoding="utf-8")
        _sync_world_model_runtime(globals()["_live_runtime_params"])
        print(f"✅ shared runtime snapshot written: {snap_path}")
    except Exception as e:
        log.debug(f"[GGUF] shared runtime snapshot write failed: {e}")

    return _llm
def _format_prompt(system: Optional[str], user: str) -> str:
    """Format a prompt using the model-appropriate chat template."""
    system = (system or "").strip()
    user = (user or "").strip()
    model_path = get_model_path()

    # Prefer the model's OWN embedded chat template (future-proof for any model);
    # fall back to filename heuristics, then the generic format.
    fam = _gguf_template_family()
    if fam is None:
        if _is_chatml_model(model_path):
            fam = "chatml"
        elif _is_llama_model(model_path):
            fam = "llama"
        elif _is_mistral_model(model_path):
            fam = "mistral"

    # Qwen / ChatML format (OpenHermes, Hermes, Dolphin, Zephyr, DeepSeek, Qwen…)
    if fam == "chatml":
        parts = []
        if system:
            parts.append(f"<|im_start|>system\n{system}<|im_end|>")
        parts.append(f"<|im_start|>user\n{user}<|im_end|>")
        # Prime the assistant turn — do NOT echo back the user message
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)

    # Llama-3 instruct format
    if fam == "llama":
        parts = ["<|begin_of_text|>"]
        if system:
            parts.append(f"<|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>")
        parts.append(f"<|start_header_id|>user<|end_header_id|>\n\n{user}<|eot_id|>")
        parts.append("<|start_header_id|>assistant<|end_header_id|>\n\n")
        return "\n".join(parts)

    # Gemma format (no system role — fold system into the user turn)
    if fam == "gemma":
        _u = f"{system}\n\n{user}" if system else user
        return f"<start_of_turn>user\n{_u}<end_of_turn>\n<start_of_turn>model\n"

    # Phi-3 format
    if fam == "phi":
        parts = []
        if system:
            parts.append(f"<|system|>\n{system}<|end|>")
        parts.append(f"<|user|>\n{user}<|end|>")
        parts.append("<|assistant|>\n")
        return "\n".join(parts)

    # Mistral / Llama-2 [INST] format
    # NOTE: do NOT add <s> here — llama.cpp prepends BOS automatically.
    # Adding it manually causes a duplicate-leading-<s> warning and hurts quality.
    if fam == "mistral":
        if system:
            return f"[INST] <<SYS>>\n{system}\n<</SYS>>\n\n{user} [/INST]"
        return f"[INST] {user} [/INST]"

    # Generic fallback (works for most models not recognized above)
    if system:
        return system + "\n\nUser:\n" + user + "\n\nELI:\n"
    return user + "\n"


def _safe_invoke_llm(llm, full_prompt: str, *, temperature, max_tokens, top_p, top_k, repeat_penalty, stop, stream, grammar):
    """
    Invoke llama.cpp safely:
    - serialize calls via _LLM_CALL_LOCK
    - if requested tokens exceed context window, retry with smaller max_tokens
    """
    attempt_max = int(max_tokens)
    last_exc = None
    bg = is_background_inference()
    # Every generation carries a cooperative abort: it yields at the next token when
    # shutdown is signalled (so teardown never blocks on a long native call) and, for
    # background work, when a foreground turn announces priority on the shared lock.
    extra = {}
    _sc = _make_stopping_criteria(bg)
    if _sc is not None:
        extra["stopping_criteria"] = _sc

    def _acquire_lock_fg_priority():
        if not bg and _fg_preempt_enabled():
            _FG_PRIORITY.set()
        try:
            _LLM_CALL_LOCK.acquire()
        finally:
            if not bg and _fg_preempt_enabled():
                _FG_PRIORITY.clear()

    for _ in range(4):
        try:
            if stream:
                _acquire_lock_fg_priority()
                try:
                    response = llm(
                        full_prompt,
                        temperature=temperature,
                        max_tokens=attempt_max,
                        top_p=top_p,
                        top_k=top_k,
                        repeat_penalty=repeat_penalty,
                        stop=stop,
                        stream=True,
                        grammar=grammar,
                        **extra,
                    )
                except Exception:
                    _LLM_CALL_LOCK.release()
                    raise

                def _locked_stream():
                    try:
                        for item in response:
                            yield item
                    finally:
                        _LLM_CALL_LOCK.release()

                return _locked_stream()

            _acquire_lock_fg_priority()
            try:
                return llm(
                    full_prompt,
                    temperature=temperature,
                    max_tokens=attempt_max,
                    top_p=top_p,
                    top_k=top_k,
                    repeat_penalty=repeat_penalty,
                    stop=stop,
                    stream=False,
                    grammar=grammar,
                    **extra,
                )
            finally:
                _LLM_CALL_LOCK.release()
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if "exceed context window" in msg or "requested tokens" in msg:
                new_attempt = max(64, attempt_max // 2)
                if new_attempt == attempt_max:
                    break
                log.debug(f"[GGUF] Context-window retry: reducing max_tokens {attempt_max} -> {new_attempt}")
                attempt_max = new_attempt
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("GGUF invocation failed")


def _estimate_prompt_tokens(llm, text: str) -> int:
    try:
        return len(llm.tokenize(text.encode("utf-8", errors="ignore")))
    except Exception:
        return max(1, len(text) // 4)


def _truncate_prompt_to_tokens(llm, text: str, max_tokens: int) -> str:
    """Shrink a prompt to <= max_tokens by keeping its HEAD and TAIL and dropping the
    middle (head = system/persona + instructions; tail = recent context + the actual
    user turn). Token-accurate when the model tokenizer is available, char-estimate
    otherwise. Used when the prompt alone overflows the context window."""
    if max_tokens <= 0:
        return text
    try:
        toks = list(llm.tokenize(text.encode("utf-8", errors="ignore")))
        if len(toks) <= max_tokens:
            return text
        head_n = max_tokens // 2
        tail_n = max(1, max_tokens - head_n)
        head = llm.detokenize(toks[:head_n]).decode("utf-8", errors="ignore")
        tail = llm.detokenize(toks[-tail_n:]).decode("utf-8", errors="ignore")
        return head + "\n…\n" + tail
    except Exception:
        pass
    # char-based fallback (~4 chars/token)
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    half = max(1, max_chars // 2)
    return text[:half] + "\n…\n" + text[-half:]


def _ctx_max_tokens(llm, full_prompt: str, reserve: int = 128) -> int:
    """
    Return the maximum tokens the model can generate for this prompt:
        n_ctx - prompt_tokens - reserve
    Can be 0 when the prompt already exhausts context.
    """
    try:
        n_ctx = llm.n_ctx()
    except Exception:
        # Prefer the env var set by runtime_settings.apply_runtime_to_env() at
        # model-load time — it reflects what the model actually loaded with,
        # which may differ from the config default if the hardware optimizer clamped it.
        import os as _os
        n_ctx = int(_os.environ.get("ELI_GGUF_N_CTX") or _os.environ.get("ELI_N_CTX") or 0)
        if n_ctx <= 0:
            from eli.core import config as _cfg
            n_ctx = _cfg.get_gguf_n_ctx()
    prompt_tokens = _estimate_prompt_tokens(llm, full_prompt)
    available = int(n_ctx) - int(prompt_tokens) - int(reserve)
    return max(0, int(available))


def available_generation_tokens(prompt: str, system: Optional[str] = None) -> int:
    """
    Public helper: how many tokens are available for generation given this prompt.
    Returns -1 if the model isn't loaded.
    """
    llm = load_model()
    if llm is None:
        return -1
    sys_text = system or ""
    full = _format_prompt(sys_text, prompt)
    return _ctx_max_tokens(llm, full)


def _generate_legacy(
    prompt: str,
    system: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    repeat_penalty: Optional[float] = None,
    stop: Optional[list] = None,
    stream: bool = False,
    grammar: Optional[LlamaGrammar] = None,
) -> Union[Generator[Dict[str, Any], None, None], Dict[str, Any]]:
    from eli.core import config

    if system is None:
        system = _canonical_eli_persona()

    if temperature is None:
        temperature = config.get_temperature()
    if top_p is None:
        top_p = config.get_top_p()
    if top_k is None:
        top_k = config.get_top_k()
    if repeat_penalty is None:
        repeat_penalty = config.get_repeat_penalty()

    llm = load_model()
    if llm is None:
        raise RuntimeError("GGUF model not available")

    full_prompt = _format_prompt(system, prompt) + _no_think_prefill(structured=False, max_tokens=max_tokens)

    available_tokens = _ctx_max_tokens(llm, full_prompt)
    if available_tokens <= 0:
        # The prompt ALONE exceeds the context window — common when a big model forced
        # ctx very small (a 20 GB MoE crushed to ctx=6144 while ELI's persona+memory
        # prompt runs ~7k tokens). TRUNCATE head+tail to fit and reserve a minimum
        # generation budget, instead of failing the turn ("Requested tokens exceed
        # context window"). Model-agnostic; head keeps the system/persona, tail keeps
        # the most recent context + the actual user turn.
        try:
            _n_ctx = int(llm.n_ctx())
        except Exception:
            _n_ctx = 16384
        _min_gen = max(96, min(512, _n_ctx // 8))
        _budget = max(256, _n_ctx - _min_gen - 96)
        _ptok_before = _estimate_prompt_tokens(llm, full_prompt)
        full_prompt = _truncate_prompt_to_tokens(llm, full_prompt, _budget)
        available_tokens = _ctx_max_tokens(llm, full_prompt)
        if available_tokens <= 0:
            available_tokens = _min_gen
        log.debug(
            f"[GGUF] prompt {_ptok_before} tok > n_ctx {_n_ctx}; truncated head+tail "
            f"to fit (gen budget ~{available_tokens} tok)")

    # max_tokens=None or -1 means "use all available context" — compute dynamically.
    if max_tokens is None or int(max_tokens) <= 0:
        max_tokens = available_tokens
    else:
        max_tokens = max(1, min(int(max_tokens), int(available_tokens)))

    stop = stop or []

    # Universal turn-boundary stops — prevent the model from running on into the
    # next turn. Chat-template tokens always apply.
    stop += ["<|im_start|>", "<|im_end|>"]

    # The natural-language role labels ("User:" / "Assistant:") are a crude guard
    # for non-templated models — and they are DELIBERATELY withheld from thinking
    # models (Qwen3 / DeepSeek-R1 / QwQ). Such a model routinely reconstructs the
    # conversation INSIDE its private <think> block, and the prompt renders history
    # as "[003] [ts] User: …" (engine.py:4412). A bare "User:" stop then fires
    # mid-think and kills generation before the model ever closes </think> or
    # writes its answer → empty reply (observed on a short, ambiguous "yes please":
    # the model halted exactly at the next "[003] … User:" label). For these models
    # the real turn terminator is the template token (<|im_end|> / <|eot_id|>),
    # added above and below — so dropping the label stops is safe.
    if not _is_thinking_model():
        stop += [
            "User:", "USER:", "\nUser:", "\nUSER:", "\n\nUser:", "\n\nUSER:",
            "Assistant:", "ASSISTANT:", "\nAssistant:", "\nASSISTANT:",
            "\n\nAssistant:", "\n\nASSISTANT:",
        ]

    _mp = get_model_path()
    if _is_mistral_model(_mp):
        stop += ["</s>", "[INST]", "[/INST]"]
    elif _is_llama_model(_mp):
        stop += ["<|eot_id|>", "<|end_of_text|>", "<|start_header_id|>"]
    else:
        stop += ["<|end|>", "<|eot_id|>"]
    if _is_chatml_model(_mp):
        stop += ["<|im_end|>"]  # already in universal but explicit for qwen

    # Deduplicate while preserving order
    seen = set()
    stop = [s for s in stop if s not in seen and not seen.add(s)]

    if stream:
        prompt_tokens = _estimate_prompt_tokens(llm, full_prompt)
        log.debug(f"[GGUF][TIMING] prompt_tokens={prompt_tokens} prompt_chars={len(full_prompt)} max_tokens={max_tokens}")
        started = time.perf_counter()
        response = _safe_invoke_llm(
            llm,
            full_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            top_k=top_k,
            repeat_penalty=repeat_penalty,
            stop=stop,
            stream=True,
            grammar=grammar,
        )
        for chunk in _stream_clean_chunks(_strip_think_stream(
                {"response": c["choices"][0]["text"]} for c in response)):
            cleaned = chunk.get("response", "")
            if cleaned:
                yield {"response": cleaned}
        log.debug(f"[GGUF][TIMING] stream_call_total={time.perf_counter()-started:.3f}s")
    else:
        prompt_tokens = _estimate_prompt_tokens(llm, full_prompt)
        log.debug(f"[GGUF][TIMING] prompt_tokens={prompt_tokens} prompt_chars={len(full_prompt)} max_tokens={max_tokens}")
        started = time.perf_counter()
        response = _safe_invoke_llm(
            llm,
            full_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            top_k=top_k,
            repeat_penalty=repeat_penalty,
            stop=stop,
            stream=False,
            grammar=grammar,
        )
        _elapsed = time.perf_counter() - started
        log.debug(f"[GGUF][TIMING] nonstream_call_total={_elapsed:.3f}s")
        _raw_text = response["choices"][0]["text"]
        log.debug(f"[GGUF][RAW_TEXT] {_raw_text[:400]!r}")
        # Record live decode speed (tokens/sec) so the speed-aware tier can cap multi-pass modes
        # on a slow/CPU-offloaded model. Prefer the model's own completion-token count; fall back
        # to a chars/4 estimate.
        try:
            _gen = int((response.get("usage") or {}).get("completion_tokens") or 0) \
                or max(1, len(_raw_text) // 4)
            if _elapsed > 0.05 and _gen >= 4:
                from eli.core.model_tier import record_speed as _rec_speed
                _rec_speed(_gen / _elapsed)
        except Exception:
            pass
        yield {"response": _clean_eli_output(_raw_text)}


_json_grammar = LlamaGrammar.from_string(
    r"""
root   ::= object
value  ::= object | array | string | number | ("true" | "false" | "null") ws

object ::=
  "{" ws (
            string ":" ws value
    ("," ws string ":" ws value)*
  )? "}" ws

array  ::=
  "[" ws (
            value
    ("," ws value)*
  )? "]" ws

string ::=
  "\"" (
    [^"\\] |
    "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])
  )* "\"" ws

number ::= ("-"? ([0-9] | [1-9] [0-9]*)) ("." [0-9]+)? ([eE] [-+]? [0-9]+)? ws
ws ::= [ \t\n]*
"""
)


def _generate_json_legacy_1(
    prompt: str,
    system: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    top_p: Optional[float] = None,
    top_k: Optional[int] = None,
    repeat_penalty: Optional[float] = None,
    **kwargs,
) -> dict:
    if system is None:
        system = _canonical_eli_persona() + " Output ONLY valid JSON."

    llm = load_model()
    if llm is None:
        raise RuntimeError("GGUF model not available")

    from eli.core import config
    if temperature is None:
        temperature = config.get_temperature()
    _full_prompt = _format_prompt(system, prompt) + _no_think_prefill(structured=True, max_tokens=max_tokens)
    _available_tokens = _ctx_max_tokens(llm, _full_prompt)
    if _available_tokens <= 0:
        # Truncate head+tail to fit rather than fail the call (same as the chat path).
        try:
            _n_ctx = int(llm.n_ctx())
        except Exception:
            _n_ctx = 16384
        _min_gen = max(96, min(512, _n_ctx // 8))
        _full_prompt = _truncate_prompt_to_tokens(llm, _full_prompt, max(256, _n_ctx - _min_gen - 96))
        _available_tokens = _ctx_max_tokens(llm, _full_prompt)
        if _available_tokens <= 0:
            _available_tokens = _min_gen
        log.debug(f"[GGUF] JSON prompt > n_ctx {_n_ctx}; truncated head+tail to fit")
    if max_tokens is None or int(max_tokens) <= 0:
        max_tokens = _available_tokens
    else:
        max_tokens = max(1, min(int(max_tokens), int(_available_tokens)))
    if top_p is None:
        top_p = config.get_top_p()
    if top_k is None:
        top_k = config.get_top_k()
    if repeat_penalty is None:
        repeat_penalty = config.get_repeat_penalty()

    full_prompt = _full_prompt
    try:
        with _LLM_CALL_LOCK:
            response = llm(
                full_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=top_p,
                top_k=top_k,
                repeat_penalty=repeat_penalty,
                grammar=_json_grammar,
                **kwargs,
            )
        content = response["choices"][0]["text"]
        return json.loads(content)
    except Exception as e:
        log.debug(f"[GGUF] JSON generation failed: {e}")
        raise RuntimeError(f"Failed to generate JSON: {e}") from e



def _chat_completion_legacy(prompt: str, system: Optional[str] = None, **kwargs) -> str:
    generator = _generate_impl(prompt=prompt, system=system, stream=False, **kwargs)
    for chunk in generator:
        _raw_chunk = chunk.get("response", "")
        log.debug(f"[GGUF][RAW_CHUNK] {_raw_chunk[:400]!r}")
        return _clean_eli_output(_raw_chunk)
    return ""


# ---- Compatibility adapters for legacy cognitive_engine callers ----

_chat_completion_impl = _chat_completion_legacy
_generate_impl = _generate_legacy
_generate_json_impl = _generate_json_legacy_1


def _coerce_chat_args(*args, **kwargs):
    system_prompt = kwargs.pop("system_prompt", None)
    user_prompt = kwargs.pop("user_prompt", None)

    if "system" in kwargs and system_prompt is None:
        system_prompt = kwargs.pop("system")
    if "prompt" in kwargs and user_prompt is None:
        user_prompt = kwargs.pop("prompt")

    if len(args) == 2 and system_prompt is None and user_prompt is None:
        system_prompt, user_prompt = args
    elif len(args) == 1 and user_prompt is None:
        user_prompt = args[0]
    elif len(args) > 2:
        if system_prompt is None:
            system_prompt = args[0]
        if user_prompt is None:
            user_prompt = args[1]

    if system_prompt is None:
        system_prompt = ""
    if user_prompt is None:
        user_prompt = ""

    return str(system_prompt), str(user_prompt), kwargs


def _normalize_call_args(*args, **kwargs):
    rest = dict(kwargs)

    system = rest.pop("system", None)
    if system is None:
        system = rest.pop("system_prompt", None)

    messages = rest.pop("messages", None)

    prompt = rest.pop("prompt", None)
    if prompt is None:
        prompt = rest.pop("user_prompt", None)

    if prompt is None:
        prompt = (
            rest.get("user_message")
            or rest.get("message")
            or rest.get("text")
            or rest.get("query")
            or rest.get("content")
        )

    if prompt is None:
        if len(args) == 2 and system is None:
            system, prompt = args
        elif len(args) >= 1:
            prompt = args[0]

    system, prompt = _eli_normalize_prompt(
        prompt=prompt,
        messages=messages,
        system=system,
        **rest,
    )

    if "num_predict" in rest and "max_tokens" not in rest:
        rest["max_tokens"] = rest.pop("num_predict")

    rest.pop("model_path", None)

    return str(system or ""), str(prompt or ""), rest


def chat_completion(*args, **kwargs) -> str:
    system_prompt, user_prompt, rest = _normalize_call_args(*args, **kwargs)
    return _chat_completion_impl(prompt=user_prompt, system=system_prompt, **rest)


def generate(*args, **kwargs):
    global _llm

    if _llm is None:
        # Auto-reload: if the model was unloaded (e.g. by a settings save),
        # try to bring it back rather than failing immediately.
        try:
            _llm = load_model()
        except Exception as _reload_err:
            raise RuntimeError(f"LLM not initialized and reload failed: {_reload_err}")
        if _llm is None:
            raise RuntimeError("LLM not initialized before generate()")

    system_prompt, user_prompt, rest = _normalize_call_args(*args, **kwargs)
    return _generate_impl(prompt=user_prompt, system=system_prompt, **rest)

def generate_json(*args, **kwargs):
    system_prompt, user_prompt, rest = _normalize_call_args(*args, **kwargs)
    return _generate_json_impl(prompt=user_prompt, system=system_prompt, **rest)

def gguf_try_infer(
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 64,
    temperature: float = 0.7,
    lock_timeout: float = 0.0,
) -> Optional[str]:
    """
    Non-blocking inference for background/auxiliary paths (e.g. HyDE).
    Tries to acquire _LLM_CALL_LOCK with `lock_timeout` seconds.
    Returns None immediately if the model is currently in use rather than blocking.
    This prevents background tasks from holding the lock and delaying main inference.
    """
    if not _LLM_CALL_LOCK.acquire(blocking=(lock_timeout > 0), timeout=lock_timeout if lock_timeout > 0 else -1):
        return None  # GGUF busy — caller should skip gracefully
    try:
        system_prompt, user_prompt, rest = _normalize_call_args(
            prompt, system=system, max_tokens=max_tokens, temperature=temperature
        )
        result = _chat_completion_impl(prompt=user_prompt, system=system_prompt, **rest)
        return result or None
    except Exception:
        return None
    finally:
        _LLM_CALL_LOCK.release()


def unload_model() -> None:
    """Cleanly unload the GGUF model to avoid Llama.__del__ crash on exit."""
    global _llm, _load_failed, _last_error
    with _LLM_CALL_LOCK:
        if _llm is not None:
            try:
                _llm.close()
            except Exception:
                pass
            _llm = None
        _load_failed = False
        _last_error = None


# Reload coordination — set by reload_model() so callers can poll
# completion without blocking the UI thread.
_reload_state: Dict[str, Any] = {
    "in_progress": False,
    "started_ts": 0.0,
    "finished_ts": 0.0,
    "ok": None,
    "error": "",
    "params": {},
}


def get_reload_state() -> Dict[str, Any]:
    """Return a copy of the current reload state for GUI/diag callers."""
    return dict(_reload_state)


def reload_model(*, await_completion: bool = True) -> Dict[str, Any]:
    """Unload and reload the GGUF model with current settings.

    Used after a settings change that requires a fresh Llama instance
    (n_ctx, n_gpu_layers, model_path, batch_size, cache_type_k/v, etc).
    Holds the LLM lock for the entire unload→load cycle so concurrent
    inference calls cannot reach a half-loaded model.

    Returns a dict mirror of `_reload_state` with the outcome.
    """
    global _reload_state
    import time as _time
    _reload_state = {
        "in_progress": True,
        "started_ts": _time.time(),
        "finished_ts": 0.0,
        "ok": None,
        "error": "",
        "params": {},
    }
    try:
        with _LLM_CALL_LOCK:
            unload_model()
            llm = load_model(force_reload=True)
            params = dict(globals().get("_live_runtime_params") or {})
            _reload_state["params"] = params
            _reload_state["ok"] = llm is not None
    except Exception as exc:
        _reload_state["ok"] = False
        _reload_state["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        _reload_state["in_progress"] = False
        _reload_state["finished_ts"] = _time.time()
    return dict(_reload_state)


def get_last_error() -> Optional[str]:
    return _last_error


def get_last_load_params() -> Dict[str, Any]:
    return dict(_last_params)


import atexit as _atexit

from eli.utils.log import get_logger
log = get_logger(__name__)

_atexit.register(unload_model)

# Aliases expected by cognitive_engine._init_gguf()
_get_model = load_model
get_model = load_model
is_available = lambda: load_model() is not None


def is_loaded() -> bool:
    global _llm
    return _llm is not None


def _sync_world_model_runtime(payload):
    """
    Keep artifacts/runtime/world_model.json aligned with the live GGUF runtime snapshot.
    """
    try:
        snap = dict(payload or {})
        if "batch_size" not in snap and "n_batch" in snap:
            snap["batch_size"] = snap.get("n_batch")
        from eli.runtime.self_model_refresh import refresh_world_model_runtime
        refresh_world_model_runtime(snap)
    except Exception as e:
        try:
            log.debug(f"[GGUF] PhaseAR2 world_model runtime sync failed: {e}")
        except Exception:
            pass


def _write_shared_runtime_snapshot(payload: Dict[str, Any]) -> None:
    try:
        from eli.core.paths import get_paths
        snap_path = Path(get_paths().artifacts_dir) / "runtime_snapshot.json"
        snap_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _sync_world_model_runtime(payload)
        log.debug(f"[GGUF] shared runtime snapshot -> {snap_path}")
    except Exception as e:
        log.debug(f"[GGUF] shared runtime snapshot write failed: {e}")


def set_runtime_override(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    payload = dict(payload or {})
    for key in ("n_ctx", "n_gpu_layers", "n_threads", "n_batch"):
        val = payload.get(key)
        if val not in (None, "", 0):
            clean[key] = int(val)
    globals()["_live_runtime_override"] = dict(clean)
    globals()["_live_runtime_params"] = dict(clean)
    try:
        _write_shared_runtime_snapshot(dict(clean))
    except Exception:
        pass
    return dict(clean)

def clear_runtime_override() -> None:
    globals().pop("_live_runtime_override", None)

def get_runtime_snapshot() -> Dict[str, Any]:
    settings = _load_runtime_settings()
    model_path = get_model_path()

    snap: Dict[str, Any] = {
        "provider": "gguf",
        "loaded": _llm is not None,
        "model_path": str(model_path) if model_path else "",
        "model_name": model_path.name if model_path else "",
        "n_ctx": 0,
        "n_gpu_layers": 0,
        "n_threads": 0,
        "n_batch": 0,
    }

    try:
        _live = globals().get("_live_runtime_override") or globals().get("_live_runtime_params") or {}
        if isinstance(_live, dict):
            if _live.get("provider"):
                snap["provider"] = str(_live.get("provider"))
            if _live.get("model_path"):
                snap["model_path"] = str(_live.get("model_path"))
            if _live.get("model_name"):
                snap["model_name"] = str(_live.get("model_name"))
            if "n_ctx" in _live:
                snap["n_ctx"] = int(_live["n_ctx"])
            if "n_gpu_layers" in _live:
                snap["n_gpu_layers"] = int(_live["n_gpu_layers"])
            if "n_threads" in _live:
                snap["n_threads"] = int(_live["n_threads"])
            if "n_batch" in _live:
                snap["n_batch"] = int(_live["n_batch"])
    except Exception:
        pass

    if not snap["n_ctx"]:
        try:
            snap["n_ctx"] = int(_runtime_value(settings, "n_ctx", "context_size", default=0) or 0)
        except Exception:
            snap["n_ctx"] = 0

    if not snap["n_gpu_layers"]:
        try:
            snap["n_gpu_layers"] = int(_runtime_value(settings, "n_gpu_layers", "gpu_layers", default=0) or 0)
        except Exception:
            snap["n_gpu_layers"] = 0

    if not snap["n_threads"]:
        try:
            snap["n_threads"] = int(_runtime_value(settings, "n_threads", "threads", "cpu_threads", default=(os.cpu_count() or 0)) or 0)
        except Exception:
            snap["n_threads"] = int(os.cpu_count() or 0)

    if not snap["n_batch"]:
        try:
            snap["n_batch"] = int(_runtime_value(settings, "n_batch", "batch", default=0) or 0)
        except Exception:
            snap["n_batch"] = 0

    def _read_int(obj, name):
        try:
            val = getattr(obj, name, None)
            if callable(val):
                val = val()
            if val in (None, "", 0):
                return None
            return int(val)
        except Exception:
            return None

    if _llm is not None:
        for attr_name, key in (
            ("n_ctx", "n_ctx"),
            ("n_batch", "n_batch"),
            ("n_threads", "n_threads"),
            ("n_gpu_layers", "n_gpu_layers"),
        ):
            val = _read_int(_llm, attr_name)
            if val is not None:
                snap[key] = val

        for container_name, mappings in (
            ("context_params", (("n_ctx", "n_ctx"), ("n_batch", "n_batch"), ("n_threads", "n_threads"))),
            ("model_params", (("n_gpu_layers", "n_gpu_layers"),)),
            ("params", (("n_ctx", "n_ctx"), ("n_batch", "n_batch"), ("n_threads", "n_threads"), ("n_gpu_layers", "n_gpu_layers"))),
        ):
            try:
                container = getattr(_llm, container_name, None)
            except Exception:
                container = None
            if container is None:
                continue
            for attr_name, key in mappings:
                val = _read_int(container, attr_name)
                if val is not None:
                    snap[key] = val

    try:
        _ov = globals().get("_live_runtime_override") or {}
        if isinstance(_ov, dict):
            if _ov.get("provider"):
                snap["provider"] = str(_ov.get("provider"))
            if _ov.get("model_path"):
                snap["model_path"] = str(_ov.get("model_path"))
            if _ov.get("model_name"):
                snap["model_name"] = str(_ov.get("model_name"))
            if "loaded" in _ov:
                snap["loaded"] = bool(_ov.get("loaded"))
            for src, dst in (
                ("n_ctx", "n_ctx"),
                ("n_gpu_layers", "n_gpu_layers"),
                ("n_threads", "n_threads"),
                ("n_batch", "n_batch"),
            ):
                val = _ov.get(src, None)
                if val not in (None, "", 0):
                    snap[dst] = int(val)
    except Exception:
        pass

    return snap


def set_live_runtime_override(payload: dict | None) -> None:
    global _live_runtime_override
    _live_runtime_override = dict(payload) if payload else None

def clear_live_runtime_override() -> None:
    global _live_runtime_override
    _live_runtime_override = None

def get_live_runtime_override():
    return _live_runtime_override

def publish_live_runtime(runtime: dict) -> dict:
    global _live_runtime_override, _live_runtime_params
    snap = dict(runtime or {})
    _live_runtime_override = dict(snap)
    _live_runtime_params = dict(snap)
    try:
        _write_shared_runtime_snapshot(dict(snap))
    except Exception:
        pass
    return snap


# Stream-aware persona/role-prefix filter on inference output.
# Delegates cleaning to the canonical output_governor to keep one source of
# truth for prefix and HR-phrase scrubbing.
def _stream_clean(text: str) -> str:
    if not isinstance(text, str):
        return text
    try:
        from eli.cognition.output_governor import govern_output as _gov
        return _gov(text)
    except Exception:
        return text


def _wrap_stream_or_text(out):
    if isinstance(out, str):
        return _stream_clean(out)

    # Streaming generator/iterator: buffer the head so split tokens like
    # " As" + " ELI:" can be cleaned before display.
    if hasattr(out, "__iter__") and not isinstance(out, (str, bytes, dict, list, tuple)):
        def gen():
            head = ""
            released = False
            for chunk in out:
                if not isinstance(chunk, str):
                    yield chunk
                    continue
                if not released:
                    head += chunk
                    if len(head) < 80 and ":" not in head and "\n" not in head:
                        continue
                    cleaned = _stream_clean(head)
                    released = True
                    if cleaned:
                        yield cleaned
                else:
                    yield _stream_clean(chunk)
            if not released and head:
                cleaned = _stream_clean(head)
                if cleaned:
                    yield cleaned
        return gen()

    if isinstance(out, dict):
        for k in ("text", "response", "content", "message", "final"):
            if isinstance(out.get(k), str):
                out[k] = _stream_clean(out[k])
    return out


def _wrap_generate(fn):
    if getattr(fn, "_eli_inference_wrapped", False):
        return fn

    def wrapped(*args, **kwargs):
        return _wrap_stream_or_text(fn(*args, **kwargs))

    wrapped._eli_inference_wrapped = True
    return wrapped


# `generate` self-recurses for auto-reload retry, so it must wrap in place (a plain
# rebind double-wraps each retry → RecursionError). Idempotent stream/text-normalise.
if callable(globals().get("generate")):
    globals()["generate"] = _wrap_generate(globals()["generate"])


# =============================================================================
# ELI ADAPTIVE GGUF COLD LOAD CONTRACT
# Cold CognitiveEngine() loads must use the same machine-adaptive behavior as
# the launcher path. A requested runtime is not "impossible"; it either succeeds
# on the current machine or fails and degrades to a lower candidate.
# =============================================================================
try:
    import inspect as _eli_adapt_inspect
    import os as _eli_adapt_os
    import subprocess as _eli_adapt_subprocess
    import time as _eli_adapt_time

    if "load_model" in globals() and not getattr(load_model, "_eli_adaptive_cold_loader", False):
        _ELI_RAW_GGUF_LOAD_MODEL = load_model
        _ELI_ADAPTIVE_LOAD_REPORT = {}

        def _eli_adapt_int(value, default):
            try:
                if value is None or value == "":
                    return int(default)
                return int(value)
            except Exception:
                return int(default)

        def _eli_probe_nvidia_vram():
            """
            Return observed GPU VRAM without assuming a specific machine.
            Shape:
              {ok, name, total_mib, free_mib}
            """
            try:
                proc = _eli_adapt_subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,memory.total,memory.free",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                    capture_output=True,
                    timeout=3,
                    check=True,
                )
                line = (proc.stdout or "").strip().splitlines()[0]
                parts = [p.strip() for p in line.split(",")]
                return {
                    "ok": True,
                    "name": parts[0] if len(parts) > 0 else "",
                    "total_mib": _eli_adapt_int(parts[1] if len(parts) > 1 else 0, 0),
                    "free_mib": _eli_adapt_int(parts[2] if len(parts) > 2 else 0, 0),
                }
            except Exception as e:
                return {
                    "ok": False,
                    "name": "",
                    "total_mib": 0,
                    "free_mib": 0,
                    "error": str(e),
                }

        def _eli_requested_runtime_from_kwargs(kwargs):
            """
            Pull requested runtime from the same source priority as raw load_model():
            explicit kwargs -> GGUF env -> hw_profile settings -> canonical settings -> config defaults.

            hw_profile_* values are preferred over canonical values when they exist —
            they are the hardware-calibrated baseline that is known to work on this
            machine without OOM.  Canonical values (user spinbox) may be larger
            sentinel values (e.g. n_gpu_layers=9999) that the GPU cannot satisfy.
            """
            try:
                _settings = _load_runtime_settings()
            except Exception:
                _settings = {}

            try:
                from eli.core import config as _eli_cfg
            except Exception:
                _eli_cfg = None

            def cfg_value(name, fallback):
                if _eli_cfg is None:
                    return fallback
                try:
                    fn = getattr(_eli_cfg, name, None)
                    if callable(fn):
                        return fn()
                except Exception:
                    pass
                return fallback

            # hw_profile_* values are the hardware-calibrated baseline.
            # Prefer them over canonical settings when the canonical looks like
            # a sentinel (>= 9000 for gpu_layers, very large for ctx).
            _hw_ctx   = _eli_adapt_int(_settings.get("hw_profile_n_ctx"), 0)
            _hw_gpu   = _eli_adapt_int(_settings.get("hw_profile_n_gpu_layers"), 0)
            _hw_batch = _eli_adapt_int(_settings.get("hw_profile_batch_size"), 0)

            _raw_ctx = _eli_adapt_int(
                kwargs.get("n_ctx")
                or kwargs.get("ctx")
                or _eli_adapt_os.environ.get("ELI_GGUF_N_CTX")
                or _runtime_value(_settings, "n_ctx", "context_size")
                or cfg_value("get_gguf_n_ctx", 32768),
                32768,
            )
            _raw_gpu = _eli_adapt_int(
                kwargs.get("n_gpu_layers")
                or kwargs.get("gpu_layers")
                or _eli_adapt_os.environ.get("ELI_GGUF_N_GPU_LAYERS")
                or _runtime_value(_settings, "gpu_layers", "n_gpu_layers")
                or cfg_value("get_gguf_n_gpu_layers", 0),
                0,
            )
            _raw_batch = _eli_adapt_int(
                kwargs.get("n_batch")
                or kwargs.get("batch_size")
                or kwargs.get("batch")
                or _eli_adapt_os.environ.get("ELI_GGUF_N_BATCH")
                or _runtime_value(_settings, "batch_size", "n_batch")
                or cfg_value("get_gguf_n_batch", 512),
                512,
            )

            # hw_profile_n_gpu_layers is the VRAM-calibrated ceiling computed
            # for THIS model on THIS machine's current free VRAM. Any resolved
            # value ABOVE it will try to offload more layers than fit and OOM
            # on the first load attempt. Clamp down to the calibrated value
            # whenever the resolved value exceeds it.
            #
            # The old guard only caught the >=9000 sentinel, which let stale
            # real-looking values slip through — e.g. a prior 7B session left
            # canonical n_gpu_layers=25, then a 24B model (calibrated to 13)
            # would request 25, OOM, and thrash through the fallback ladder.
            # hw_profile=99 ("all layers fit") is never exceeded by a real
            # layer count, so a smaller real request is correctly left alone.
            if _hw_gpu > 0 and _raw_gpu > _hw_gpu:
                _raw_gpu = _hw_gpu
            if _hw_ctx > 0 and _raw_ctx > _hw_ctx * 1.5:
                # Canonical ctx is significantly larger than hw-recommended —
                # use hw_profile as base to avoid OOM on the first attempt.
                _raw_ctx = _hw_ctx
            if _hw_batch > 0 and _raw_batch > _hw_batch * 2:
                _raw_batch = _hw_batch

            return {
                "n_ctx": _raw_ctx,
                "n_gpu_layers": _raw_gpu,
                "n_batch": _raw_batch,
            }

        def _eli_unique_candidates(candidates):
            seen = set()
            out = []
            for c in candidates:
                if not c.get("override"):
                    key = ("raw",)
                else:
                    key = (int(c["n_ctx"]), int(c["n_gpu_layers"]), int(c["n_batch"]))
                if key in seen:
                    continue
                seen.add(key)
                out.append(c)
            return out

        def _eli_build_adaptive_candidates(requested, gpu):
            """
            Machine-adaptive fallback ladder.

            It does not hard-code the user's machine. It uses observed VRAM to
            choose a conservative candidate, then adds generic degradation steps.
            """
            req_ctx = max(512, int(requested.get("n_ctx") or 32768))
            req_gpu = max(0, int(requested.get("n_gpu_layers") or 0))
            req_batch = max(32, int(requested.get("n_batch") or 512))

            total = int(gpu.get("total_mib") or 0)
            free = int(gpu.get("free_mib") or 0)
            basis = free if free > 0 else total

            # VRAM-proportional ctx cap — replaces hardcoded tier values.
            # Allocates 40% of free VRAM to the KV cache after a 512 MiB
            # floor for CUDA context overhead.  KV at fp16 for a typical
            # 7B-class model is ~160 KB/token (32 layers × 8 GQA heads ×
            # 128 head_dim × 2 bytes × 2 for K+V with 25% headroom).
            # Aligned to 2048-token granularity for llama.cpp.
            _kv_bytes_per_token = 163840  # 160 KiB / token
            _kv_budget_mb = max(0, int(basis * 0.40) - 512) if basis > 0 else 0
            _vram_ctx = (
                max(2048, (_kv_budget_mb * 1024 * 1024 // _kv_bytes_per_token // 2048) * 2048)
                if _kv_budget_mb > 0 else 2048
            )

            candidates = []

            # Known-good first: if a previous successful load published its
            # effective config (the GUI smart-fit, or any prior load), try THAT
            # before the raw requested config. This is what makes a reload —
            # notably the text-model restore after a vision hot-swap — return to
            # the profile that already fit (e.g. ctx=22528/gpu=99) instead of
            # starting from the raw oversized request (ctx=30720) and adaptively
            # collapsing to a near-CPU config (gpu_layers=16) for the rest of the
            # session. Only prepended when present + valid; the ladder below is
            # the safety net if it no longer fits.
            try:
                _ov = globals().get("_live_runtime_override") or {}
                _ov_ctx = int(_ov.get("n_ctx") or 0)
                _ov_gpu = _ov.get("n_gpu_layers")
                if _ov_ctx >= 512 and _ov_gpu is not None:
                    candidates.append({
                        "label": "live-override (last known-good)",
                        "override": True,
                        "n_ctx": _ov_ctx,
                        "n_gpu_layers": max(0, int(_ov_gpu)),
                        "n_batch": max(32, int(_ov.get("n_batch") or req_batch)),
                    })
            except Exception:
                pass

            candidates.append({
                "label": "requested/raw-no-override",
                "override": False,
            })

            # VRAM-aware conservative candidate. This is threshold-based, not
            # machine-name based.  ctx cap is derived from the VRAM formula
            # above — no hardcoded context-window values.
            if basis > 0:
                if basis <= 4096:
                    candidates.append({
                        "label": "adaptive-vram<=4g",
                        "override": True,
                        "n_ctx": min(req_ctx, _vram_ctx),
                        "n_gpu_layers": min(req_gpu, max(0, req_gpu // 4)),
                        "n_batch": min(req_batch, 256),
                    })
                elif basis <= 6144:
                    candidates.append({
                        "label": "adaptive-vram<=6g",
                        "override": True,
                        "n_ctx": min(req_ctx, _vram_ctx),
                        "n_gpu_layers": min(req_gpu, max(0, req_gpu // 3)),
                        "n_batch": min(req_batch, 256),
                    })
                elif basis <= 8192:
                    candidates.append({
                        "label": "adaptive-vram<=8g",
                        "override": True,
                        "n_ctx": min(req_ctx, _vram_ctx),
                        "n_gpu_layers": min(req_gpu, max(0, req_gpu // 2)),
                        "n_batch": min(req_batch, max(128, req_batch // 2)),
                    })
                else:
                    candidates.append({
                        "label": "adaptive-vram>8g",
                        "override": True,
                        "n_ctx": req_ctx,
                        "n_gpu_layers": req_gpu,
                        "n_batch": req_batch,
                    })

            # Generic fallback ladder. Important candidate for 32k/21/512 on
            # low-VRAM machines: 16k / quarter GPU layers / 256 batch.
            generic = [
                (req_ctx, max(0, req_gpu // 2), min(req_batch, 256), "generic-half-gpu"),
                (min(req_ctx, 16384), max(0, req_gpu // 2), min(req_batch, 256), "generic-16k-half-gpu"),
                (min(req_ctx, 16384), max(0, req_gpu // 4), min(req_batch, 256), "generic-16k-quarter-gpu"),
                (min(req_ctx, 16384), max(0, req_gpu // 6), min(req_batch, 192), "generic-16k-sixth-gpu"),
                (min(req_ctx, 16384), max(0, req_gpu // 8), min(req_batch, 128), "generic-16k-eighth-gpu"),
                (min(req_ctx, 16384), 0, min(req_batch, 128), "generic-16k-cpu"),
                (min(req_ctx, 8192), max(0, req_gpu // 4), min(req_batch, 128), "generic-8k-quarter-gpu"),
                (min(req_ctx, 8192), 0, min(req_batch, 128), "generic-8k-cpu"),
                (min(req_ctx, 4096), 0, min(req_batch, 64), "generic-4k-cpu"),
            ]

            for ctx, gpu_layers, batch, label in generic:
                candidates.append({
                    "label": label,
                    "override": True,
                    "n_ctx": max(512, int(ctx)),
                    "n_gpu_layers": max(0, int(gpu_layers)),
                    "n_batch": max(32, int(batch)),
                })

            return _eli_unique_candidates(candidates)

        def _eli_apply_candidate_to_kwargs(raw_loader, kwargs, candidate):
            if not candidate.get("override"):
                return dict(kwargs)

            sig = _eli_adapt_inspect.signature(raw_loader)
            params = sig.parameters
            accepts_kwargs = any(p.kind == p.VAR_KEYWORD for p in params.values())

            def supported(name):
                return accepts_kwargs or name in params

            out = dict(kwargs)

            if supported("n_ctx"):
                out["n_ctx"] = int(candidate["n_ctx"])
            elif supported("ctx"):
                out["ctx"] = int(candidate["n_ctx"])

            if supported("n_gpu_layers"):
                out["n_gpu_layers"] = int(candidate["n_gpu_layers"])
            elif supported("gpu_layers"):
                out["gpu_layers"] = int(candidate["n_gpu_layers"])

            if supported("n_batch"):
                out["n_batch"] = int(candidate["n_batch"])
            elif supported("batch_size"):
                out["batch_size"] = int(candidate["n_batch"])
            elif supported("batch"):
                out["batch"] = int(candidate["n_batch"])

            return out

        def _eli_try_unload_after_failed_load():
            try:
                fn = globals().get("unload_model")
                if callable(fn):
                    fn()
            except Exception:
                pass

        def _eli_candidate_env_overrides(candidate):
            """
            The raw GGUF load_model() reads runtime params from env/settings
            internally and usually does not accept n_ctx/n_gpu_layers/n_batch
            kwargs. Therefore fallback candidates must temporarily override the
            GGUF env vars around the raw load call.
            """
            if not candidate.get("override"):
                return {}

            return {
                "ELI_GGUF_N_CTX": str(int(candidate["n_ctx"])),
                "ELI_GGUF_N_GPU_LAYERS": str(int(candidate["n_gpu_layers"])),
                "ELI_GGUF_N_BATCH": str(int(candidate["n_batch"])),
            }

        def _eli_call_raw_load_with_candidate(args, kwargs, candidate):
            overrides = _eli_candidate_env_overrides(candidate)
            if not overrides:
                return _ELI_RAW_GGUF_LOAD_MODEL(*args, **kwargs)

            old_env = {k: _eli_adapt_os.environ.get(k) for k in overrides}

            try:
                for k, v in overrides.items():
                    _eli_adapt_os.environ[k] = str(v)
                return _ELI_RAW_GGUF_LOAD_MODEL(*args, **kwargs)
            finally:
                for k, old in old_env.items():
                    if old is None:
                        _eli_adapt_os.environ.pop(k, None)
                    else:
                        _eli_adapt_os.environ[k] = old

        def get_adaptive_load_report():
            return dict(_ELI_ADAPTIVE_LOAD_REPORT)

        def load_model(*args, **kwargs):
            """
            Adaptive wrapper around the original GGUF load_model().

            Contract:
            - Try requested/raw config first.
            - If llama_context creation fails, retry lower candidates.
            - Never call a failed candidate impossible.
            - Return the first successful load.
            """
            global _ELI_ADAPTIVE_LOAD_REPORT

            if kwargs.pop("_eli_disable_adaptive_cold_loader", False):
                return _ELI_RAW_GGUF_LOAD_MODEL(*args, **kwargs)

            # Fast-path: model already in memory, no force_reload requested.
            # Skip VRAM probe + candidate loop entirely — just return the cached
            # instance.  Avoids "[GGUF][ADAPTIVE] load attempt 1" noise on every
            # inference call when the model is healthy.
            _force = kwargs.get("force_reload", False) or (args and args[0])
            if _llm is not None and not _force:
                return _llm

            requested = _eli_requested_runtime_from_kwargs(kwargs)
            gpu = _eli_probe_nvidia_vram()
            candidates = _eli_build_adaptive_candidates(requested, gpu)

            _ELI_ADAPTIVE_LOAD_REPORT = {
                "ok": False,
                "requested": requested,
                "gpu_probe": gpu,
                "attempts": [],
                "selected": None,
                "started_at": _eli_adapt_time.time(),
            }

            last_error = None

            for idx, candidate in enumerate(candidates, start=1):
                call_kwargs = _eli_apply_candidate_to_kwargs(
                    _ELI_RAW_GGUF_LOAD_MODEL,
                    kwargs,
                    candidate,
                )

                attempt = {
                    "attempt": idx,
                    "label": candidate.get("label", ""),
                    "override": bool(candidate.get("override")),
                    "n_ctx": candidate.get("n_ctx"),
                    "n_gpu_layers": candidate.get("n_gpu_layers"),
                    "n_batch": candidate.get("n_batch"),
                    "ok": False,
                    "error": "",
                }

                try:
                    if candidate.get("override"):
                        log.debug(
                            "[GGUF][ADAPTIVE] load attempt "
                            f"{idx}: ctx={candidate.get('n_ctx')} "
                            f"gpu_layers={candidate.get('n_gpu_layers')} "
                            f"batch={candidate.get('n_batch')} "
                            f"label={candidate.get('label')}",
                        )
                    else:
                        log.debug(
                            "[GGUF][ADAPTIVE] load attempt "
                            f"{idx}: requested/raw config label={candidate.get('label')}",
                        )

                    result = _eli_call_raw_load_with_candidate(args, call_kwargs, candidate)

                    attempt["ok"] = True
                    _ELI_ADAPTIVE_LOAD_REPORT["ok"] = True
                    _ELI_ADAPTIVE_LOAD_REPORT["selected"] = attempt
                    _ELI_ADAPTIVE_LOAD_REPORT["attempts"].append(attempt)
                    _ELI_ADAPTIVE_LOAD_REPORT["finished_at"] = _eli_adapt_time.time()

                    log.debug(
                        "[GGUF][ADAPTIVE] load OK "
                        f"attempt={idx} label={candidate.get('label')}",
                    )
                    return result

                except Exception as e:
                    last_error = e
                    attempt["error"] = str(e)
                    _ELI_ADAPTIVE_LOAD_REPORT["attempts"].append(attempt)

                    log.debug(
                        "[GGUF][ADAPTIVE] load failed on current runtime "
                        f"attempt={idx} label={candidate.get('label')} error={e}",
                    )

                    _eli_try_unload_after_failed_load()

            _ELI_ADAPTIVE_LOAD_REPORT["finished_at"] = _eli_adapt_time.time()

            if last_error is not None:
                raise last_error

            return _ELI_RAW_GGUF_LOAD_MODEL(*args, **kwargs)

        load_model._eli_adaptive_cold_loader = True

        log.debug("[GGUF][ADAPTIVE] cold load fallback wrapper installed")

except Exception as _eli_adaptive_loader_err:
    log.debug(f"[GGUF][ADAPTIVE] cold load fallback wrapper failed: {_eli_adaptive_loader_err}")

# =============================================================================
# ELI EFFECTIVE GGUF RUNTIME SNAPSHOT CONTRACT
# Separates requested runtime config from effective loaded config.
# This is machine-adaptive: no GPU/VRAM configuration is treated as impossible.
# =============================================================================
try:
    if "load_model" in globals() and not getattr(load_model, "_eli_effective_runtime_snapshot_contract", False):
        import json as _eli_eff_json
        import os as _eli_eff_os
        import time as _eli_eff_time
        from pathlib import Path as _eli_eff_Path

        _ELI_EFFECTIVE_PREV_LOAD_MODEL = load_model
        _ELI_EFFECTIVE_PREV_GET_RUNTIME_SNAPSHOT = globals().get("get_runtime_snapshot")
        _ELI_EFFECTIVE_RUNTIME_REPORT = {}

        def _eli_eff_int(value, default=0):
            try:
                if value is None or value == "":
                    return int(default)
                return int(value)
            except Exception:
                return int(default)

        def _eli_eff_snapshot_path():
            try:
                from eli.core.paths import get_paths
                return _eli_eff_Path(get_paths().artifacts_dir) / "runtime_snapshot.json"
            except Exception:
                return _eli_eff_Path("artifacts/runtime_snapshot.json")

        def _eli_eff_read_json(path):
            try:
                p = _eli_eff_Path(path)
                if p.exists():
                    return _eli_eff_json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
            return {}

        def _eli_eff_write_json(path, payload):
            try:
                p = _eli_eff_Path(path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(_eli_eff_json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                try:
                    log.debug(f"[GGUF][EFFECTIVE] runtime snapshot write failed: {e}")
                except Exception:
                    pass

        def _eli_eff_call_or_attr(obj, name):
            try:
                val = getattr(obj, name, None)
                if callable(val):
                    return val()
                return val
            except Exception:
                return None

        def _eli_eff_nested_int(obj, containers):
            for container_name, names in containers:
                try:
                    container = getattr(obj, container_name, None)
                    if container is None:
                        continue
                    for name in names:
                        val = _eli_eff_call_or_attr(container, name)
                        if val not in (None, ""):
                            return _eli_eff_int(val, 0)
                except Exception:
                    continue
            return 0

        def _eli_eff_llm_int(llm, key):
            if llm is None:
                return 0

            direct_names = {
                "n_ctx": ("n_ctx", "ctx", "context_size"),
                "n_gpu_layers": ("n_gpu_layers", "gpu_layers"),
                "n_threads": ("n_threads", "threads"),
                "n_batch": ("n_batch", "batch_size", "batch"),
            }.get(key, (key,))

            for name in direct_names:
                val = _eli_eff_call_or_attr(llm, name)
                if val not in (None, ""):
                    return _eli_eff_int(val, 0)

            nested = {
                "n_ctx": (
                    ("context_params", ("n_ctx",)),
                    ("params", ("n_ctx",)),
                ),
                "n_gpu_layers": (
                    ("model_params", ("n_gpu_layers", "gpu_layers")),
                    ("params", ("n_gpu_layers", "gpu_layers")),
                ),
                "n_threads": (
                    ("context_params", ("n_threads", "threads")),
                    ("params", ("n_threads", "threads")),
                ),
                "n_batch": (
                    ("context_params", ("n_batch", "batch_size", "batch")),
                    ("params", ("n_batch", "batch_size", "batch")),
                ),
            }.get(key, ())

            return _eli_eff_nested_int(llm, nested)

        def _eli_eff_current_model_path(existing=None):
            existing = existing or {}
            for key in ("model_path", "path"):
                val = existing.get(key)
                if val:
                    return str(val)
            try:
                val = globals().get("MODEL_PATH") or globals().get("model_path")
                if val:
                    return str(val)
            except Exception:
                pass
            try:
                from eli.core import config
                val = config.get_gguf_model_path()
                if val:
                    return str(val)
            except Exception:
                pass
            return ""

        def _eli_eff_requested(existing=None, adaptive=None):
            existing = existing or {}
            adaptive = adaptive or {}

            previous_requested = existing.get("requested") if isinstance(existing.get("requested"), dict) else {}
            adaptive_requested = adaptive.get("requested") if isinstance(adaptive.get("requested"), dict) else {}

            # Important:
            # The raw loader writes its resolved load parameters to runtime_snapshot.json
            # before this effective wrapper rewrites the snapshot. Those raw top-level
            # values are the best evidence of what was actually requested by the GGUF
            # load path. Legacy aliases such as ELI_N_GPU_LAYERS can be stale and may
            # not match the resolved llama.cpp load parameters, so they are last-resort
            # fallbacks only.
            raw_snapshot_requested = {
                "n_ctx": existing.get("requested_n_ctx") or existing.get("n_ctx"),
                "n_gpu_layers": existing.get("requested_n_gpu_layers") or existing.get("n_gpu_layers"),
                "n_threads": existing.get("requested_n_threads") or existing.get("n_threads"),
                "n_batch": existing.get("requested_n_batch") or existing.get("n_batch") or existing.get("batch_size"),
            }

            def pick(key, gguf_env, *legacy_envs):
                return _eli_eff_int(
                    raw_snapshot_requested.get(key)
                    or adaptive_requested.get(key)
                    or previous_requested.get(key)
                    or _eli_eff_os.environ.get(gguf_env)
                    or next((_eli_eff_os.environ.get(k) for k in legacy_envs if _eli_eff_os.environ.get(k)), None)
                    or 0
                )

            return {
                "n_ctx": pick("n_ctx", "ELI_GGUF_N_CTX", "ELI_N_CTX"),
                "n_gpu_layers": pick("n_gpu_layers", "ELI_GGUF_N_GPU_LAYERS", "ELI_N_GPU_LAYERS", "ELI_GPU_LAYERS"),
                "n_threads": pick("n_threads", "ELI_GGUF_N_THREADS", "ELI_N_THREADS"),
                "n_batch": pick("n_batch", "ELI_GGUF_N_BATCH", "ELI_BATCH_SIZE"),
            }

        def _eli_eff_adaptive_report():
            try:
                fn = globals().get("get_adaptive_load_report")
                if callable(fn):
                    rep = fn()
                    if isinstance(rep, dict):
                        return dict(rep)
            except Exception:
                pass
            return {}

        def _eli_eff_effective(llm=None, existing=None, adaptive=None):
            existing = existing or {}
            adaptive = adaptive or {}
            selected = adaptive.get("selected") if isinstance(adaptive.get("selected"), dict) else {}
            previous_effective = existing.get("effective") if isinstance(existing.get("effective"), dict) else {}

            effective = {}
            for key in ("n_ctx", "n_gpu_layers", "n_threads", "n_batch"):
                selected_value = selected.get(key)
                live_value = _eli_eff_llm_int(llm, key)
                previous_value = previous_effective.get(key)
                legacy_value = existing.get(key)

                effective[key] = _eli_eff_int(
                    selected_value if selected_value not in (None, "") else
                    live_value if live_value not in (None, "") else
                    previous_value if previous_value not in (None, "") else
                    legacy_value if legacy_value not in (None, "") else
                    0
                )

            # If the runtime explicitly reports that GPU offload is unsupported,
            # effective GPU layers must be 0 even if requested settings were >0.
            _gpu_supported = existing.get("gpu_offload_supported")
            if isinstance(_gpu_supported, str):
                _low = _gpu_supported.strip().lower()
                if _low in ("false", "0", "no", "off"):
                    _gpu_supported = False
                elif _low in ("true", "1", "yes", "on"):
                    _gpu_supported = True
            if _gpu_supported is False and _eli_eff_int(effective.get("n_gpu_layers"), 0) > 0:
                effective["n_gpu_layers"] = 0

            return effective

        def _eli_eff_build_runtime_report(llm=None, *, source="unknown", existing=None):
            existing = existing or _eli_eff_read_json(_eli_eff_snapshot_path())
            adaptive = _eli_eff_adaptive_report()
            requested = _eli_eff_requested(existing, adaptive)
            effective = _eli_eff_effective(llm, existing, adaptive)

            # If a value truly cannot be read from live/runtime evidence, preserve
            # requested value as fallback. IMPORTANT: effective `0` is valid for
            # n_gpu_layers when GPU offload is unavailable; do not overwrite it.
            for key in ("n_ctx", "n_gpu_layers", "n_threads", "n_batch"):
                val = effective.get(key, None)
                if val in (None, ""):
                    effective[key] = requested.get(key, 0)

            model_path = _eli_eff_current_model_path(existing)
            model_name = ""
            try:
                model_name = _eli_eff_Path(model_path).name if model_path else str(existing.get("model_name") or "")
            except Exception:
                model_name = str(existing.get("model_name") or "")

            payload = dict(existing)
            payload.update({
                "provider": "gguf",
                "model_path": model_path,
                "model_name": model_name,
                "loaded": llm is not None or bool(existing.get("loaded")),
                "pid": _eli_eff_os.getpid(),
                "ts": _eli_eff_time.time(),
                "runtime_contract": "requested_effective_split",
                "runtime_source": source,
                "requested": requested,
                "effective": effective,
                "adaptive_load_report": adaptive,
                "gpu_offload_supported": existing.get("gpu_offload_supported"),
                "load_mode": "GPU" if int(effective.get("n_gpu_layers") or 0) > 0 else "CPU",
                # Legacy compatibility: top-level runtime values now mean effective.
                "n_ctx": int(effective.get("n_ctx") or 0),
                "n_gpu_layers": int(effective.get("n_gpu_layers") or 0),
                "n_threads": int(effective.get("n_threads") or 0),
                "n_batch": int(effective.get("n_batch") or 0),
                "batch_size": int(effective.get("n_batch") or 0),
                # Explicit requested aliases for old renderers/tests.
                "requested_n_ctx": int(requested.get("n_ctx") or 0),
                "requested_n_gpu_layers": int(requested.get("n_gpu_layers") or 0),
                "requested_n_threads": int(requested.get("n_threads") or 0),
                "requested_n_batch": int(requested.get("n_batch") or 0),
            })
            return payload

        def get_effective_runtime_report():
            return dict(_ELI_EFFECTIVE_RUNTIME_REPORT or _eli_eff_build_runtime_report(globals().get("_llm"), source="report_read"))

        def get_runtime_snapshot():
            global _ELI_EFFECTIVE_RUNTIME_REPORT
            llm = globals().get("_llm")
            existing = _eli_eff_read_json(_eli_eff_snapshot_path())
            payload = _eli_eff_build_runtime_report(llm, source="get_runtime_snapshot", existing=existing)
            _ELI_EFFECTIVE_RUNTIME_REPORT = dict(payload)
            return dict(payload)

        def load_model(*args, **kwargs):
            global _ELI_EFFECTIVE_RUNTIME_REPORT
            llm = _ELI_EFFECTIVE_PREV_LOAD_MODEL(*args, **kwargs)
            payload = _eli_eff_build_runtime_report(llm, source="load_model_effective")
            _ELI_EFFECTIVE_RUNTIME_REPORT = dict(payload)
            _eli_eff_write_json(_eli_eff_snapshot_path(), payload)
            try:
                log.debug(
                    "[GGUF][EFFECTIVE] "
                    f"requested ctx={payload['requested'].get('n_ctx')} "
                    f"gpu_layers={payload['requested'].get('n_gpu_layers')} "
                    f"batch={payload['requested'].get('n_batch')} -> "
                    f"effective ctx={payload['effective'].get('n_ctx')} "
                    f"gpu_layers={payload['effective'].get('n_gpu_layers')} "
                    f"batch={payload['effective'].get('n_batch')}",
                )
            except Exception:
                pass
            return llm

        load_model._eli_effective_runtime_snapshot_contract = True
        globals()["get_runtime_snapshot"] = get_runtime_snapshot
        globals()["get_effective_runtime_report"] = get_effective_runtime_report
        globals()["load_model"] = load_model

        try:
            log.debug("[GGUF][EFFECTIVE] requested/effective runtime snapshot contract installed")
        except Exception:
            pass

except Exception as _eli_effective_runtime_err:
    try:
        log.debug(f"[GGUF][EFFECTIVE] runtime snapshot contract failed: {_eli_effective_runtime_err}")
    except Exception:
        pass
