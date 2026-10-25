"""
GGUF inference for ELI — model-agnostic.

Detects the loaded model's family from its filename and applies the correct chat
template (Mistral/Mixtral [INST], Llama-3 headers, Qwen/ChatML, etc.). No model
name, size, or path is assumed; everything resolves from config/env.

(no hardcoded paths, no forced parameter lowering):
- KV-cache quantization comes from the settings `cache_type_k` / `cache_type_v`: empty is fp16,
  anything quantized loads as q8_0 (eli.core.gguf_sizes.effective_cache_type). It holds nearly
  twice the context of fp16 in the same memory.

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

# Logger for safety-wrapper suppressed-exception reporting (used before the
# module's main logger exists; must be defined at the top of the file).
import logging as _swlog_logging
_SWLOG = _swlog_logging.getLogger(__name__)

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
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



# Set when llama.cpp refused a quantized KV cache in this process (no flash attention on this
# backend or build): from then on the default cache is asked for and fitted for.
_kv_cache_refused = False


def _cache_types(settings: Dict[str, Any]) -> tuple:
    """(K, V) cache types the load asks for and every fit assumes: the operator's settings,
    or the default once llama.cpp has refused them here."""
    if _kv_cache_refused:
        return "", ""
    from eli.core.gguf_sizes import cache_setting
    return (cache_setting(_runtime_value(settings, "cache_type_k", "type_k", default="")),
            cache_setting(_runtime_value(settings, "cache_type_v", "type_v", default="")))


def _requested_ctx(settings: Dict[str, Any], model_path) -> int:
    """The context to load this model with: the operator's (env, then settings), else auto for
    this model on this machine. Never 0, which llama.cpp reads as the model's whole trained
    context; with nothing measurable, the smallest window."""
    n_ctx = _env_int("ELI_GGUF_N_CTX", None) or _as_int(_runtime_value(settings, "n_ctx", "context_size"), 0)
    if int(n_ctx or 0) <= 0:
        try:
            from eli.core.hardware_profile import auto_ctx_for
            n_ctx = int(auto_ctx_for(model_path) or 0)
        except Exception:
            log.debug("[GGUF] auto context unavailable", exc_info=True)
            n_ctx = 0
    return int(n_ctx) if int(n_ctx or 0) > 0 else 2048

_last_error: Optional[str] = None
_last_params: Dict[str, Any] = {}

def get_model_path() -> Optional[Path]:
    from eli.core.paths import resolve_runtime_path

    # Strongest override: explicit file path. If explicitly set and missing, do not silently fall back.
    env_path = os.environ.get("ELI_GGUF_MODEL_PATH")
    if env_path:
        p = resolve_runtime_path(env_path)
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
                p = resolve_runtime_path(str(path_value))
                if p.exists():
                    return p

    # Next: (models dir, filename) pair
    model_name = os.environ.get("ELI_GGUF_MODEL")
    models_dir = os.environ.get("ELI_MODELS_DIR")
    if model_name and models_dir:
        cand = (resolve_runtime_path(models_dir) / model_name).resolve()
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
        _SWLOG.debug("suppressed exception", exc_info=True)

    from eli.core import config
    path = config.get("gguf_model_path")
    if path:
        p = resolve_runtime_path(str(path))
        if p.exists():
            return p

    # Last resort: the model this process is already running. The GUI hands it over via
    # gguf_inference._llm, not the settings keys, so lookups came back empty mid-answer. Explicit
    # config still wins. globals().get because _live_runtime_params only exists after a load.
    for _src in (globals().get("_live_runtime_override"),
                 globals().get("_live_runtime_params")):
        try:
            _p = (_src or {}).get("model_path")
            if _p:
                p = resolve_runtime_path(str(_p))
                if p.exists():
                    return p
        except Exception:
            _SWLOG.debug("suppressed exception", exc_info=True)

    # And the snapshot the loader writes to disk, which survives a reload of this
    # module when the in-memory override does not.
    try:
        import json as _json_rs
        from eli.core.paths import get_paths as _gp_rs
        _snap_path = _gp_rs().artifacts_dir / "runtime_snapshot.json"
        if _snap_path.exists():
            _p = (_json_rs.loads(_snap_path.read_text(encoding="utf-8")) or {}).get("model_path")
            if _p:
                p = resolve_runtime_path(str(_p))
                if p.exists():
                    return p
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)

    return None


def _loaded_model_path_str() -> str:
    _ov = globals().get("_live_runtime_override") or globals().get("_live_runtime_params") or {}
    path = str(_ov.get("model_path") or _ov.get("model_name") or "").strip()
    if path:
        return path
    try:
        return str(get_model_path() or "")
    except Exception:
        return ""


def _resolve_family_for_loaded(*, path: Optional[Path] = None) -> Optional[str]:
    """Template → architecture → filename — never brand-first."""
    from eli.cognition.model_identity import resolve_chat_family
    md = _gguf_model_metadata()
    return resolve_chat_family(
        metadata=md,
        path=path or _loaded_model_path_str() or get_model_path(),
    )


def _is_mistral_model(model_path: Optional[Path]) -> bool:
    return _resolve_family_for_loaded(path=model_path) == "mistral"


def _is_chatml_model(model_path: Optional[Path]) -> bool:
    return _resolve_family_for_loaded(path=model_path) == "chatml"


def _is_llama_model(model_path: Optional[Path]) -> bool:
    return _resolve_family_for_loaded(path=model_path) == "llama"


def _is_glm_model(model_path: Optional[Path] = None) -> bool:
    """GLM / ChatGLM — from embedded template / architecture, not filename brands."""
    from eli.cognition.model_identity import is_glm_model as _glm
    md = _gguf_model_metadata() if model_path is None else {}
    if model_path is not None and not md:
        try:
            from eli.cognition.model_load_diagnostics import gguf_metadata
            md = gguf_metadata(model_path) or {}
        except Exception:
            md = {}
    return _glm(
        metadata=md,
        path=model_path if model_path is not None else _loaded_model_path_str(),
    )


def _is_thinking_model(model_path: Optional[Path] = None) -> bool:
    """Does this model default to a <think>…</think> channel?

    Model-agnostic order: chat template → architecture default → behavior
    retry elsewhere. Filename brand lists are intentionally unused so a renamed
    GGUF still gets the correct no-think prefill on quick/utility calls.
    """
    from eli.cognition.model_identity import is_thinking_model as _think
    if model_path is not None:
        try:
            from eli.cognition.model_load_diagnostics import gguf_metadata, gguf_architecture
            md = gguf_metadata(model_path) or {}
            arch = gguf_architecture(model_path)
            return _think(metadata=md, architecture=arch, path=model_path)
        except Exception:
            return _think(path=model_path)
    md = _gguf_model_metadata()
    return _think(metadata=md, path=_loaded_model_path_str())


# Thread-local "force no-think" scope for calls that already have all the facts and only phrase them
# (EXPLAIN_* synthesis); otherwise a <think> block burns the whole budget and returns empty. Use
# `with force_no_think():`. Thread-local so a concurrent agent's call is unaffected.
_NO_THINK_TLS = threading.local()


def _force_no_think_active() -> bool:
    return bool(getattr(_NO_THINK_TLS, "force", False))


@contextmanager
def force_no_think():
    """Within this scope, every GGUF chat call on THIS thread skips its <think> block."""
    _prev = getattr(_NO_THINK_TLS, "force", False)
    _NO_THINK_TLS.force = True
    try:
        yield
    finally:
        _NO_THINK_TLS.force = _prev


def _thinking_wanted(*, structured: bool, max_tokens) -> bool:
    """Whether this call may reason before it answers.

    Never for structured/JSON calls, small-budget calls (< 1024 tokens: judge, summary, routing),
    Quick mode (a "hey" once thought for 316 s) or inside a `force_no_think()` scope, whatever the
    Think toggle says; otherwise the Think toggle (ELI_MODEL_THINK) decides. This turn's mode
    first: the env var is process-global, so under concurrent API requests it holds whichever
    turn wrote last and only counts for calls made outside a turn."""
    if _force_no_think_active():
        return False
    try:
        _small = 0 < int(max_tokens or 0) < 1024
    except Exception:
        _small = False
    try:
        from eli.kernel.request_context import reasoning_mode_var as _turn_mode
        _mode = _turn_mode.get()
    except Exception:
        _mode = None
    if _mode is None:
        _mode = os.environ.get("ELI_CURRENT_REASONING_MODE", "")
    if structured or _small or str(_mode).strip().lower() == "quick":
        return False
    return os.environ.get("ELI_MODEL_THINK", "").strip().lower() not in ("0", "false", "no", "off")


def _no_think_prefill(*, structured: bool, max_tokens) -> str:
    """The assistant-turn prefill for a model whose prompt comes from the family formats (no
    template of its own): a CLOSED empty <think> block when the call must not reason, so a
    utility call doesn't spend its budget thinking (the A3B routed everything to fallback.chat
    and lost session summaries that way). Reliable across <think> families; the /no_think
    soft-switch is ignored by some Qwen3 quants. '' for non-reasoning models or when reasoning is
    wanted. A model with its own template is switched through it instead (_prompt_for_call)."""
    _glm = _is_glm_model()
    _closed_think = "<think>\n\n</think>\n\n"
    _open_think = "<think>\n\n"
    # Utility scopes must suppress thinking even on models the heuristics miss (e.g. Ornith):
    # otherwise the whole budget burns inside an unclosed block and cleaning returns empty.
    if _force_no_think_active():
        return _closed_think
    if not _is_thinking_model():
        return ""
    disable = not _thinking_wanted(structured=structured, max_tokens=max_tokens)
    if _glm:
        return _closed_think if disable else _open_think
    return _closed_think if disable else ""


def _gguf_model_metadata() -> dict:
    """Embedded metadata of the loaded model (`_llm.metadata`); {} if unavailable."""
    try:
        llm = globals().get("_llm")
        md = getattr(llm, "metadata", None) if llm is not None else None
        return md if isinstance(md, dict) else {}
    except Exception:
        return {}


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
        _SWLOG.debug("suppressed exception", exc_info=True)

    try:
        from eli.core import config
        val = (config.get_persona() or "").strip()
        if val:
            return val
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)

    return "You are ELI, a local reasoning and automation assistant. Be direct, accurate, grounded, privacy-preserving, and useful."

def _marker_pattern(marker: str, *, closing: bool) -> str:
    """A reasoning marker as a pattern: a tag-like marker (`<think>`) also matches its attribute
    and spacing variants; any other (`<|channel>thought`) matches as written."""
    m = re.fullmatch(r"</?([A-Za-z_][\w-]*)>", marker.strip())
    if m:
        name = re.escape(m.group(1))
        return rf"</{name}\s*>" if closing else rf"<{name}\b[^>]*>"
    return re.escape(marker.strip())


def _reasoning_patterns() -> list:
    """(open, close) patterns of the reasoning markers in use: the loaded model's own, from its
    template (eli/cognition/chat_template.py), then the common <think> forms."""
    from eli.cognition.chat_template import reasoning_markers
    return [(_marker_pattern(o, closing=False), _marker_pattern(c, closing=True))
            for o, c in reasoning_markers()]


def _strip_think_text(t: str) -> str:
    """Remove a reasoning block from text before user-visible cleaning.

    Closed blocks, a block cut off before it closed, and a close marker whose opener the model
    never wrote (everything before it was reasoning). The markers are the model's own where its
    template has them; a no-op when none are present."""
    t = str(t or "")
    if not t.strip():
        return t
    pats = _reasoning_patterns()
    if not any(re.search(o, t, re.I) or re.search(c, t, re.I) for o, c in pats):
        return t
    for o, c in pats:
        t = re.sub(rf"(?is){o}.*?{c}", "", t)
    for o, c in pats:
        if re.search(c, t, re.I):
            t = re.split(c, t, flags=re.I)[-1]
        elif re.search(o, t, re.I):
            t = re.split(o, t, flags=re.I)[0]
    for o, c in pats:
        t = re.sub(rf"(?i){o}|{c}", "", t)
    return t.strip()


def _clean_eli_output(text: str) -> str:
    from eli.cognition.model_output_tokens import (
        PERSONA_DRIFT_PREFIXES,
        strip_persona_drift_prefix,
        strip_special_tokens,
    )
    t = _strip_think_text(str(text or ""))
    t = strip_special_tokens(t)
    t = t.replace("Assistant:", "ELI:").replace("assistant:", "ELI:").replace("AI:", "ELI:")
    t = t.replace("assistant\n", "")
    t = t.strip()
    t = re.sub(r"^\s*ELI:\s*", "", t)
    # Weak or short-context models sometimes echo ELI's prompt scaffolding instead of answering. Cut
    # the reply at the first such marker so it is never shown.
    _scaffold_markers = (
        "--- BRIEF ---", "--- END HISTORY", "END HISTORY ---", "--- END BRIEF",
        "--- CONVERSATION HISTORY", "--- CONVERSACTION HISTORY", "CONVERSACTION HISTORY",
        "Knowledge graph context:", "Reply to the latest user message",
        "CRITICAL: NEVER copy", "NEVER copy or verbatim",
    )
    _low = t.lower()
    _hits = [_low.find(m.lower()) for m in _scaffold_markers if m.lower() in _low]
    if _hits:
        t = t[:min(_hits)].strip()
    # Strip canned completion-style prefixes the model outputs in prompt-continuation mode
    t = re.sub(r"^\s*Short\s+answer\s*:\s*", "", t, flags=re.I)
    t = re.sub(r"^\s*(?:Answer|Response|Reply)\s*:\s*", "", t, flags=re.I)
    t = t.strip()

    bad_heads = PERSONA_DRIFT_PREFIXES
    low = t.lower().strip()
    if any(low.startswith(p) for p in bad_heads):
        log.debug(f"[GGUF][CLEAN] Persona drift stripped: {t[:80]!r}")
        salvaged = strip_persona_drift_prefix(t)
        if salvaged:
            return salvaged
        return t  # empty responses are worse than imperfect ones
    # Strip model meta-commentary appended after main response
    t = re.sub(r'\s*\(Note:[^)]{0,400}\)', '', t, flags=re.I).strip()
    t = re.sub(r'\s*\[Note:[^\]]{0,400}\]', '', t, flags=re.I).strip()
    t = re.sub(r'\s*\(Note:.*$', '', t, flags=re.I | re.DOTALL).strip()

    if not t.strip():
        log.debug(f"[GGUF][CLEAN] Empty after cleaning, returning raw fallback")
        # Strip think + meta-commentary from the fallback too — NEVER surface raw
        # chain-of-thought just because the cleaned text came out empty (e.g. the
        # model spent its whole budget thinking).
        from eli.cognition.model_output_tokens import (
            contains_hard_cut_marker,
            strip_special_tokens as _strip_fallback,
        )
        raw_fallback = _strip_think_text(str(text or "")).strip()
        raw_fallback = re.sub(r'\s*\(Note:.*$', '', raw_fallback, flags=re.I | re.DOTALL).strip()
        # Multimodal EOI floods (`<image|>` only) must stay empty — do not
        # re-surface the marker via the empty-clean fallback.
        if contains_hard_cut_marker(raw_fallback):
            raw_fallback = _strip_fallback(raw_fallback)
        return raw_fallback if raw_fallback else ''
    return t.strip()

def _strip_think_stream(chunks):
    """Suppress a leading reasoning block from a token stream (the model's own markers, from its
    template, and the <think> forms). Engages ONLY when the output begins with an opener, so it
    adds no latency and is a pure pass-through otherwise."""
    from eli.cognition.chat_template import reasoning_markers
    pats = _reasoning_patterns()
    # what an opener starts with, to know whether a short head may still become one
    heads = [re.sub(r">$", "", o.strip()).lower() if re.fullmatch(r"<[A-Za-z_][\w-]*>", o.strip())
             else o.strip().lower() for o, _c in reasoning_markers()]
    longest = max((len(h) for h in heads), default=0) + 8
    buf = ""
    mode = "detect"  # detect → suppress → pass  (or detect → pass)
    closer = None
    for chunk in chunks:
        raw = chunk.get("response", "") if isinstance(chunk, dict) else str(chunk or "")
        if not raw:
            continue
        if mode == "pass":
            yield {"response": raw}
            continue
        buf += raw
        low = buf.lstrip().lower()
        if mode == "detect":
            opened = next((c for (o, c) in pats if re.match(o, buf.lstrip(), re.I)), None)
            if opened is not None:
                mode, closer = "suppress", opened
            elif (low == "" or any(h.startswith(low) for h in heads)) and len(buf) < longest:
                continue          # still undecided: leading whitespace or part of an opener
            else:
                mode = "pass"
                yield {"response": buf}
                buf = ""
                continue
        if mode == "suppress" and re.search(closer, buf, re.I):
            after = re.split(closer, buf, maxsplit=1, flags=re.I)[-1]
            buf, mode = "", "pass"
            if after.strip():
                yield {"response": after}
    if buf and mode != "suppress":
        yield {"response": buf}


def _stream_clean_chunks(chunks):
    """True streaming cleaner; hold only obvious role prefixes.

    Head text gets a full clean. Mid-stream chunks only strip special/hard-cut
    markers and MUST preserve whitespace — llama.cpp emits BPE pieces like
    ``" "`` / ``" word"``, and calling ``.strip()`` on each chunk concatenates
    English into ``Qwena3bMoelikelyoperates…``.
    """
    from eli.cognition.model_output_tokens import (
        contains_hard_cut_marker,
        strip_special_tokens,
    )

    head_buffer = ""
    started = False
    max_head = 80
    possible_prefixes = {
        "", "e", "el", "eli", "eli:",
        "a", "as", "ass", "assi", "assis", "assist", "assista",
        "assistan", "assistant", "assistant:",
        "ai", "ai:",
    }

    def _mid_sanitize(raw: str) -> str:
        if contains_hard_cut_marker(raw):
            return strip_special_tokens(raw, strip_edges=False)
        # Fast path: most chunks have no scaffolding — keep bytes intact.
        if "<" not in raw and "[" not in raw:
            return raw
        return strip_special_tokens(raw, strip_edges=False)

    for chunk in chunks:
        raw = chunk.get("response", "") if isinstance(chunk, dict) else str(chunk or "")
        if not raw:
            continue
        if started:
            if contains_hard_cut_marker(raw):
                cleaned = _mid_sanitize(raw)
                if cleaned:
                    yield {"response": cleaned}
                return
            cleaned = _mid_sanitize(raw)
            if cleaned:
                yield {"response": cleaned}
            continue
        head_buffer += raw
        log.debug(f"[GGUF][RAW_HEAD] {head_buffer[:400]!r}")
        if contains_hard_cut_marker(head_buffer):
            cleaned = _clean_eli_output(head_buffer)
            if cleaned:
                yield {"response": cleaned}
            return
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
            fallback = re.sub(r"^\s*(?:ELI|Assistant|AI)\s*:\s*", "", head_buffer, flags=re.I)
            # Preserve interior whitespace; only trim role-label leftovers.
            fallback = strip_special_tokens(fallback, strip_edges=False)
            if fallback.strip():
                yield {"response": fallback}

    if not started and head_buffer:
        cleaned = _clean_eli_output(head_buffer)
        if cleaned:
            yield {"response": cleaned}


_llm: Optional[Llama] = None
_live_runtime_override: Optional[Dict[str, Any]] = None
# What the last load asked for and what it loaded (requested/effective, the plan, per device), as
# load_model writes it to runtime_snapshot.json.
_ELI_EFFECTIVE_RUNTIME_REPORT: Dict[str, Any] = {}
_load_failed: bool = False  # sentinel: don't retry after a confirmed failure
_last_load_error: Optional[str] = None
try:
    from eli.runtime.native_locks import LLAMA_CPP_NATIVE_LOCK as _LLM_CALL_LOCK
except Exception:
    _LLM_CALL_LOCK = threading.RLock()

# Foreground preemption. Generation serialises on _LLM_CALL_LOCK, so a slow background job
# (news, insight, morning report) could stall the user's turn for minutes. A foreground call
# sets _FG_PRIORITY and background calls yield at the next token. ELI_FG_PREEMPT=0 turns it off.
# The same event as native_locks.FOREGROUND_WAITING, which the embedder raises for the user's turn too.
try:
    from eli.runtime.native_locks import FOREGROUND_WAITING as _FG_PRIORITY
except Exception:
    _FG_PRIORITY = threading.Event()
# Keep the ctypes abort callback alive for the process lifetime.
_LLAMA_ABORT_CB = None
# Set at shutdown to abort every in-flight generation at the next token. A native call can't be
# killed mid-thread, so without this unload_model() waited 20-30 min for the lock.
_SHUTDOWN = threading.Event()
# Set when the user clicks Stop during chat generation. Cooperative abort at the
# next token — same mechanism as shutdown, without tearing down the model.
_USER_CANCEL = threading.Event()
_bg_tls = threading.local()


def signal_shutdown() -> None:
    """Abort ALL in-flight generations at the next token (foreground and background).
    Idempotent; called first thing in engine shutdown."""
    _SHUTDOWN.set()


def clear_shutdown() -> None:
    _SHUTDOWN.clear()


def request_cancel_generation() -> None:
    """Abort the current user-facing generation at the next token."""
    _USER_CANCEL.set()


def clear_cancel_generation() -> None:
    _USER_CANCEL.clear()


def is_cancel_requested() -> bool:
    return _USER_CANCEL.is_set()


def is_shutting_down() -> bool:
    return _SHUTDOWN.is_set()


@contextmanager
def allow_one_call_during_shutdown():
    """Exempt one deliberate call (the shutdown-time session summary) from the
    abort-on-shutdown check below, without affecting any other caller."""
    _bg_tls.allow_during_shutdown = True
    try:
        yield
    finally:
        _bg_tls.allow_during_shutdown = False


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
    signalled (aborts ANY call, except one deliberately exempted via
    allow_one_call_during_shutdown), the user clicked Stop (aborts ANY call), or — for
    BACKGROUND calls with preemption enabled — a foreground turn is waiting on the
    shared lock."""
    if _USER_CANCEL.is_set():
        return True
    if _SHUTDOWN.is_set() and not getattr(_bg_tls, "allow_during_shutdown", False):
        return True
    return bool(background) and _fg_preempt_enabled() and _FG_PRIORITY.is_set()


def _install_llama_abort_callback(llm) -> None:
    """Abort prompt prefill and token generation when shutdown/cancel is signalled.

    StoppingCriteria only runs between output tokens; llama_set_abort_callback
    interrupts llama_decode during the prompt prefill as well — so closing the
    GUI during a 1000+ token CPU prefill returns promptly instead of hanging.

    One callback serves every context and is never replaced: llama.cpp keeps only the pointer. A
    fresh one per load dropped the previous model's callback while a background generation was
    still decoding on that model, and its next decode called freed memory (SIGSEGV in llama_decode).
    """
    global _LLAMA_ABORT_CB
    try:
        import ctypes
        from llama_cpp import llama_cpp as _lc

        if _LLAMA_ABORT_CB is None:
            @_lc.ggml_abort_callback
            def _abort_cb(_data):
                return bool(_should_abort_generation(is_background_inference()))

            _LLAMA_ABORT_CB = _abort_cb
        _lc.llama_set_abort_callback(llm.ctx, _LLAMA_ABORT_CB, ctypes.c_void_p(None))
    except Exception:
        _SWLOG.debug("llama abort callback install failed", exc_info=True)


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


def load_request(model_path, settings: Optional[Dict[str, Any]] = None, **overrides):
    """What the operator asked to load this model with (eli/core/load_plan.Request): the environment
    first, then the settings, then `overrides` (the window's own boxes). Context 0 is auto; a GPU-layer
    count counts only for the model and context it was set for (pinned_gpu_layers_for_model), else as
    many layers as fit."""
    from eli.core import config
    from eli.core.load_plan import Request
    from eli.core.runtime_settings import _resolve_gpu_split, pinned_gpu_layers_for_model
    settings = settings if settings is not None else _load_runtime_settings()
    n_ctx = int(_env_int("ELI_GGUF_N_CTX", None) or _as_int(_runtime_value(settings, "n_ctx", "context_size"), 0) or 0)
    n_gpu_layers = _env_int("ELI_GGUF_N_GPU_LAYERS", None)
    if n_gpu_layers is None:
        try:
            n_gpu_layers = pinned_gpu_layers_for_model(model_path, settings, current_ctx=n_ctx or None)
        except Exception:
            log.debug("[GGUF] gpu-layer pin provenance unavailable", exc_info=True)
    ts, main_gpu, split_mode = _resolve_gpu_split(settings)
    _force_cpu = str(os.environ.get("ELI_FORCE_CPU", "")).strip().lower() in ("1", "true", "yes", "on")
    cache_k, cache_v = _cache_types(settings)
    req = Request(
        model_path=str(model_path),
        n_ctx=n_ctx,
        n_gpu_layers=None if n_gpu_layers is None else int(n_gpu_layers),
        n_batch=int(_env_int("ELI_GGUF_N_BATCH", None)
                    or _as_int(_runtime_value(settings, "batch_size", "n_batch"), config.get_gguf_n_batch())),
        n_threads=int(_env_int("ELI_GGUF_THREADS", None) or _as_int(_runtime_value(settings, "cpu_threads", "n_threads"), 0)),
        cache_type_k=cache_k, cache_type_v=cache_v,
        use_mmap=_as_bool(_runtime_value(settings, "use_mmap", default=True), True),
        use_mlock=_as_bool(_runtime_value(settings, "use_mlock", default=False), False),
        fit_priority=str(os.environ.get("ELI_FIT_PRIORITY") or settings.get("fit_priority") or ""),
        tensor_split=str(os.environ.get("ELI_GGUF_TENSOR_SPLIT") or ts or ""),
        gpu_devices=str(os.environ.get("ELI_GPU_DEVICES") or settings.get("gpu_devices") or ""),
        split_mode=str(os.environ.get("ELI_GGUF_SPLIT_MODE") or split_mode or ""),
        main_gpu=_as_int(os.environ.get("ELI_GGUF_MAIN_GPU") or main_gpu, 0),
        cpu_only=_force_cpu or str(settings.get("compute_mode") or "").strip().lower() == "cpu"
        or str(os.environ.get("ELI_FORCE_GPU_LAYERS", "")).strip() == "0",
    )
    for key, value in overrides.items():
        if value is not None and hasattr(req, key):
            setattr(req, key, value)
    return req


def _as_bool(value, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _new_llama(plan):
    """llama.cpp's model built as the plan says, experts kept in RAM where it says so."""
    from llama_cpp import Llama
    from eli.cognition.model_load_diagnostics import llama_accepts
    kwargs = llama_accepts(Llama, plan.llama_kwargs())
    if plan.experts_in_ram is None or int(plan.n_gpu_layers) <= 0:
        return Llama(**kwargs)
    from eli.core import moe_offload
    layers = None if int(plan.experts_in_ram) >= int(plan.blocks) else int(plan.experts_in_ram)
    with moe_offload.expert_offload_params(layers):
        return Llama(**kwargs)


def _build_with_plan(plan, req, model_path):
    """Load the plan. A load that runs out of memory (another program took some between the plan and
    the load) is planned again from what is free then; a file or runtime this build cannot read is
    explained and not retried."""
    from dataclasses import replace as _replace
    from eli.core import load_plan
    from eli.cognition.model_load_diagnostics import (
        ModelLoadError, capture_llama_log, deactivate_gpu_pack, explain_load_failure,
        gpu_pack_is_too_old, harden_llama_destructor, is_retryable_load_failure, kv_cache_refused)
    harden_llama_destructor()
    dropped_pack = False
    for attempt in range(1, 4):
        lines: list = []
        try:
            with capture_llama_log() as lines:
                return _new_llama(plan), lines, plan, req
        except Exception as err:
            if (plan.cache_type_k or plan.cache_type_v) and kv_cache_refused(lines) and not _kv_cache_refused:
                globals()["_kv_cache_refused"] = True
                log.warning("[LOAD_PLAN] llama.cpp refused a %s KV cache here (it needs flash attention); "
                            "planning again with the default cache", plan.cache_type_k or plan.cache_type_v)
                req = _replace(req, cache_type_k="", cache_type_v="")
                plan = load_plan.plan(req) or load_plan.as_asked(req)
                continue
            if not is_retryable_load_failure(lines):
                if not dropped_pack and gpu_pack_is_too_old() and deactivate_gpu_pack():
                    # the pack in the way of a model only the bundled runtime reads: drop it and try that
                    dropped_pack = True
                    globals()["Llama"] = __import__("importlib").import_module("llama_cpp").Llama
                    log.warning("[LOAD_PLAN] the GPU pack cannot read this model; loading on the bundled "
                                "runtime (slower; reinstall the pack once a build reads it)")
                    plan = load_plan.plan(req) or load_plan.as_asked(req)
                    continue
                msg = explain_load_failure(err, lines, model_path, gpu_layers=plan.n_gpu_layers)
                globals()["_last_load_error"] = msg
                e = ModelLoadError(msg)
                e.retryable = False
                raise e from err
            msg = explain_load_failure(err, lines, model_path, gpu_layers=plan.n_gpu_layers)
            if attempt >= 3 or (plan.n_gpu_layers == 0 and not plan.devices):     # already on the processor
                globals()["_last_load_error"] = msg
                e = ModelLoadError(msg)
                e.retryable = True
                raise e from err
            fresh = load_plan.plan(req)
            if fresh is None or (fresh.n_gpu_layers, fresh.n_ctx, fresh.n_batch, fresh.tensor_split) == (
                    plan.n_gpu_layers, plan.n_ctx, plan.n_batch, plan.tensor_split):
                fresh = load_plan.on_processor(req)
            log.warning("[LOAD_PLAN] the load did not fit (%s); planned again for the memory free now: %s",
                        msg.splitlines()[0][:200], fresh.describe())
            plan = fresh
    raise RuntimeError("unreachable")


def _note_headroom() -> None:
    """After a generation call: what each card gave up since the load (eli/core/load_plan.py)."""
    try:
        from eli.core import load_plan
        load_plan.note_headroom()
    except Exception:
        log.debug("[LOAD_PLAN] headroom not measured", exc_info=True)


def _requested_and_effective(plan, llm) -> tuple:
    """What the load was asked for (the plan's starting point: the user's settings with "auto"
    worked out) and what is loaded, read from the live model where it says, the plan where not:
    llama.cpp can change a value as it builds the model, and the report must say what is."""
    def _live(read, fallback):
        try:
            value = read()
            return int(value) if value is not None else int(fallback)
        except Exception:
            return int(fallback)
    effective = {
        "n_ctx": _live(lambda: llm.n_ctx(), plan.n_ctx),
        "n_gpu_layers": _live(lambda: llm.model_params.n_gpu_layers, plan.n_gpu_layers),
        "n_threads": _live(lambda: llm.n_threads, plan.n_threads),
        "n_batch": _live(lambda: llm.n_batch, plan.n_batch),
    }
    asked = dict(plan.asked or {})
    requested = {"n_ctx": int(asked.get("n_ctx") or effective["n_ctx"]),
                 "n_gpu_layers": int(asked.get("n_gpu_layers") if asked.get("n_gpu_layers") is not None
                                     else effective["n_gpu_layers"]),
                 "n_threads": effective["n_threads"],
                 "n_batch": int(asked.get("n_batch") or effective["n_batch"])}
    return requested, effective


def load_model(force_reload: bool = False, *, request=None):
    """The loaded model, loading it if needed: the configured model, or `request`
    (eli/core/load_plan.Request), with the plan for this machine now (eli/core/load_plan.py)."""
    global _llm, _ELI_EFFECTIVE_RUNTIME_REPORT

    import time as _time
    from pathlib import Path as _Path
    from eli.core import load_plan

    if _llm is not None and not force_reload and request is None:
        return _llm

    # Resolve the path before dropping the handle: a reload that can't succeed must not destroy the
    # model that is loaded.
    settings = _load_runtime_settings()
    model_path = request.model_path if request is not None else get_model_path()
    if not model_path:
        raise FileNotFoundError("No GGUF model path configured")
    model_path = _Path(model_path).expanduser().resolve()
    if not model_path.exists():
        raise FileNotFoundError(f"GGUF model not found: {model_path}")

    from eli.cognition.model_load_diagnostics import (
        ModelLoadError as _ModelLoadError,
        preflight_gguf_model as _preflight_gguf_model,
    )
    _preflight_msg = _preflight_gguf_model(model_path)
    if _preflight_msg:
        globals()["_last_load_error"] = _preflight_msg
        _pe = _ModelLoadError(_preflight_msg)
        _pe.retryable = False
        raise _pe

    from eli.core.llama_cpu_compat import preflight_runtime as _cpu_preflight
    _cpu_msg = _cpu_preflight()
    if _cpu_msg:
        globals()["_last_load_error"] = _cpu_msg
        _ce = _ModelLoadError(_cpu_msg)
        _ce.retryable = False
        raise _ce

    _llm = None

    # Co-resident vision: the small fast model loads first so the plan below sees the memory it takes.
    if bool(_runtime_value(settings, "vision_coresident", default=False)):
        try:
            from eli.perception import vision as _eli_vision
            _rok, _rreason = _eli_vision.load_resident_fast_model()
            if not _rok:
                log.debug(f"[GGUF] co-resident vision: fast model not loaded ({_rreason})")
        except Exception as _co_err:
            log.debug(f"[GGUF] co-resident vision setup skipped: {_co_err}")

    req = request if request is not None else load_request(model_path, settings)
    req.model_path = str(model_path)
    plan = load_plan.plan(req) or load_plan.as_asked(req)
    for note in plan.notes:
        log.info("[LOAD_PLAN] %s", note)
    log.info("[LOAD_PLAN] %s: %s", model_path.name, plan.describe())

    _pre_load_rss = 0
    try:
        from eli.runtime.inference_footprint import capture_process_rss_bytes as _cap_rss
        _pre_load_rss = int(_cap_rss())
    except Exception:
        log.debug("[GGUF] pre-load RSS capture skipped", exc_info=True)

    _llm, _load_log, plan, req = _build_with_plan(plan, req, model_path)
    try:
        load_plan.watch_headroom(plan)       # what llama.cpp takes on each card from here is measured
    except Exception:
        log.debug("[LOAD_PLAN] headroom watch not started", exc_info=True)

    _kv_loaded = None
    try:
        # llama.cpp's own KV size for this model replaces the estimate from its header
        from eli.core.gguf_sizes import record_load_report, loaded_cache_types
        record_load_report(model_path, _load_log)
        _kv_loaded = loaded_cache_types(_load_log)
    except Exception:
        log.debug("[GGUF] KV report not recorded", exc_info=True)

    _held = ""
    if plan.notes and not any("fit as asked" in n for n in plan.notes):
        try:
            from eli.core.hardware_profile import describe_vram_holders, vram_holders
            _held = describe_vram_holders(vram_holders(), total_mb=sum(d.total_mb for d in plan.devices) or None)
        except Exception:
            log.debug("[GGUF] VRAM holders unavailable", exc_info=True)
        if _held:
            log.warning(f"[LOAD_PLAN] other programs are using GPU memory: {_held}. Close them or have "
                        f"them release the GPU, then reload the model to get the rest of your settings.")

    requested, effective = _requested_and_effective(plan, _llm)
    gpu_supported = bool(plan.devices)
    payload = {
        "provider": "gguf",
        "model_path": str(model_path),
        "model_name": model_path.name,
        "loaded": True,
        "pid": os.getpid(),
        "ts": _time.time(),
        "runtime_contract": "requested_effective_split",
        "runtime_source": "load_model_effective",
        "requested": requested,
        "effective": effective,
        "load_plan": {"text": plan.describe(), "notes": list(plan.notes), "measured": bool(plan.measured),
                      "devices": [{"index": d.index, "name": d.name, "description": d.description,
                                   "free_mb": d.free_mb, "total_mb": d.total_mb,
                                   "planned_mb": round(plan.use_mb.get(d.index, 0.0))} for d in plan.devices]},
        "gpu_offload_supported": gpu_supported,
        "load_mode": "GPU" if plan.n_gpu_layers != 0 else "CPU",          # -1: every layer
        "n_ctx": effective["n_ctx"],
        "n_gpu_layers": effective["n_gpu_layers"],
        "n_threads": effective["n_threads"],
        "n_batch": effective["n_batch"],
        "batch_size": effective["n_batch"],
        "requested_n_ctx": requested["n_ctx"],
        "requested_n_gpu_layers": requested["n_gpu_layers"],
        "requested_n_threads": requested["n_threads"],
        "requested_n_batch": requested["n_batch"],
        # the cache llama.cpp says it made; what was asked for when it did not say
        "cache_type_k": (_kv_loaded[0] if _kv_loaded else (plan.cache_type_k or "f16")),
        "cache_type_v": (_kv_loaded[1] if _kv_loaded else (plan.cache_type_v or plan.cache_type_k or "f16")),
        "flash_attn": bool(plan.flash_attn),
        "tensor_split": plan.tensor_split,
        "split_mode": plan.split_mode,
        "main_gpu": plan.main_gpu,
        "moe_expert_offload": plan.experts_in_ram is not None,
        "moe_experts_in_ram_layers": plan.experts_in_ram,
        "vram_free_mb_at_load": int(sum(d.free_mb for d in plan.devices)) if plan.devices else None,
        "vram_held_by_others": _held,
    }
    globals()["_last_params"] = {
        "n_ctx": effective["n_ctx"], "n_gpu_layers": effective["n_gpu_layers"],
        "n_threads": effective["n_threads"], "n_batch": effective["n_batch"],
        "model_path": str(model_path), "load_mode": payload["load_mode"],
        "moe_expert_offload": payload["moe_expert_offload"],
    }
    try:
        from eli.runtime.inference_footprint import record_load_memory as _rec_mem
        payload["live_inference_memory"] = _rec_mem(_llm, pre_load_rss_bytes=_pre_load_rss)
    except Exception:
        log.debug("[GGUF] live inference memory record skipped", exc_info=True)
    globals()["_live_runtime_params"] = dict(payload)
    globals()["_last_load_error"] = None
    _ELI_EFFECTIVE_RUNTIME_REPORT = dict(payload)
    _write_shared_runtime_snapshot(payload)
    _install_llama_abort_callback(_llm)
    return _llm


def _format_prompt(system: Optional[str], user: str, *, think: Optional[bool] = None) -> str:
    """Format a prompt in the loaded model's own chat format.

    The model's own template (`tokenizer.chat_template`, rendered by chat_template) first; the
    family formats only for a file without one. `think` switches reasoning through that
    template; None leaves the template's own default.

    Also notes where the part that does not depend on the message ends (_stable_prefix_var):
    the model state there is kept and reused by the next prompt that starts the same way.
    """
    text = _format_chat(system, user, think=think)
    fixed = ""
    if str(system or "").strip():
        try:
            a, b = _format_chat(system, "A", think=think), _format_chat(system, "B", think=think)
            fixed = os.path.commonprefix([a, b])
            fixed = fixed if text.startswith(fixed) else ""
        except Exception:
            _SWLOG.debug("fixed prompt part not found", exc_info=True)
    _stable_prefix_var.set(fixed)
    return text


def _model_template():
    """The loaded model's own chat template (chat_template.Template), or None for a file that
    carries none that renders."""
    try:
        from eli.cognition import chat_template
        return chat_template.for_model(globals().get("_llm"), _gguf_model_metadata())
    except Exception:
        _SWLOG.debug("model template unavailable", exc_info=True)
        return None


def _prompt_for_call(system: Optional[str], prompt: str, *, structured: bool, max_tokens) -> str:
    """The prompt for one call, with reasoning on or off as the call needs (_thinking_wanted):
    through the model's own template when it has one, else the family format and a prefill."""
    think = _thinking_wanted(structured=structured, max_tokens=max_tokens)
    tpl = _model_template()
    if tpl is not None:
        from eli.cognition.chat_template import render_prompt
        if render_prompt(tpl, str(system or "").strip(), str(prompt or "").strip(), think=think) is not None:
            return _format_prompt(system, prompt, think=think)
    return _format_prompt(system, prompt) + _no_think_prefill(structured=structured, max_tokens=max_tokens)


def _format_chat(system: Optional[str], user: str, *, think: Optional[bool] = None) -> str:
    """The loaded model's own template filled in; the family format when it has none."""
    system = (system or "").strip()
    user = (user or "").strip()
    tpl = _model_template()
    if tpl is not None:
        from eli.cognition.chat_template import render_prompt
        rendered = render_prompt(tpl, system, user, think=think)
        if rendered is not None:
            return rendered
    model_path = get_model_path()
    fam = _resolve_family_for_loaded(path=model_path)

    # GLM / ChatGLM — [gMASK]<|system|>…<|user|>…<|assistant|> (must precede phi)
    if fam == "glm":
        parts = ["[gMASK]"]
        if system:
            parts.append(f"<|system|>{system}")
        parts.append(f"<|user|>{user}")
        parts.append("<|assistant|>")
        return "".join(parts)

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


def _fit_generation_budget(llm, full_prompt: str, max_tokens):
    """Return (prompt, max_tokens) that fit the model's ACTUAL context window.

    Two independent things have to hold, and previously each was enforced in some
    call paths and not others:

      1. prompt + generation <= effective n_ctx. If the requested generation does
         not fit, it is reduced — never the other way around.
      2. the prompt alone must leave room to say something. A prompt that fills
         the window is not a small answer, it is no answer: llama.cpp raises and
         the turn collapses to whatever fallback the caller has.

    The generation floor is derived from the window (n_ctx // 8, bounded), not a
    constant — on a 4k model that is 512 tokens, on a 128k model 512 as well, and
    the prompt gives way instead. Nothing here caps how large a context ELI can
    use: it reads whatever the model actually loaded with, so a 100B model on a
    128k window gets a 128k budget.
    """
    try:
        n_ctx = int(_effective_ctx_limit(llm))
    except Exception:
        return full_prompt, int(max_tokens)
    if n_ctx <= 0:
        return full_prompt, int(max_tokens)

    gen_floor = max(96, min(512, n_ctx // 8))
    reserve = 32                      # BOS/EOS and template slack
    try:
        prompt_tokens = int(_estimate_prompt_tokens(llm, full_prompt))
    except Exception:
        return full_prompt, int(max_tokens)

    # (2) The prompt has eaten the room to answer — shrink it, keeping the head
    # (system/persona) and the tail (recent context + the actual user turn).
    if prompt_tokens > n_ctx - gen_floor - reserve:
        budget = max(256, n_ctx - gen_floor - reserve)
        try:
            full_prompt = _truncate_prompt_to_tokens(llm, full_prompt, budget)
            after = int(_estimate_prompt_tokens(llm, full_prompt))
            log.debug("[GGUF][FIT] prompt %d tok > window %d; truncated head+tail to %d",
                      prompt_tokens, n_ctx, after)
            prompt_tokens = after
        except Exception:
            log.debug("[GGUF][FIT] prompt truncation failed", exc_info=True)

    # (1) Never ask for more than is left.
    available = max(1, n_ctx - prompt_tokens - reserve)
    requested = int(max_tokens) if max_tokens and int(max_tokens) > 0 else available
    fitted = max(1, min(requested, available))
    if fitted < requested:
        log.debug("[GGUF][FIT] max_tokens %d -> %d (prompt %d, window %d)",
                  requested, fitted, prompt_tokens, n_ctx)
    return full_prompt, fitted


# ── The model's state at the end of a prompt's fixed part ─────────────────────
#
# Most of what ELI sends the model is the same from one call to the next: the system prompt
# (persona, rules, the turn's evidence) for each pass of a turn, the action list for the intent
# resolver. llama.cpp re-reads only what follows the first difference from what it last read, but
# a hybrid model (qwen35moe: most of its layers carry a running state, not an attention cache)
# cannot roll that state back, so every call read everything again: 62 s for a 7k-token prompt on
# a 35B model, for each pass of a Normal-mode turn. The state at the end of the fixed part is
# saved and given back to the next prompt that starts the same way (measured 2026-10-14 on that
# model: 135 MiB for 7k tokens, saved in 0.08 s, restored in 0.02 s; the second pass then took 2 s
# and gave the same next token as reading the whole prompt). Attention-only models gain too:
# the resolver's call in between used to push the turn's prompt out of their cache.
_stable_prefix_var: "ContextVar[str]" = ContextVar("eli_stable_prompt_prefix", default="")
_SAVED_STATES: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()
# The saved states together take no more than this share of the memory free when one is added,
# and no more than two full contexts' worth of state.
_SAVED_STATES_SHARE = 0.125


def forget_saved_states() -> None:
    """Drop every saved model state (a model was unloaded or replaced)."""
    _SAVED_STATES.clear()


def _saved_states_room() -> int:
    try:
        import psutil
        return int(psutil.virtual_memory().available * _SAVED_STATES_SHARE)
    except Exception:
        return 0


def _save_seq_state(llm) -> Optional[Any]:
    """The model's memory for its one sequence, as bytes llama.cpp can take back."""
    import ctypes
    from llama_cpp import llama_cpp as _lc
    size = int(_lc.llama_state_seq_get_size(llm._ctx.ctx, 0))
    if size <= 0:
        return None
    buf = (ctypes.c_uint8 * size)()
    got = int(_lc.llama_state_seq_get_data(llm._ctx.ctx, buf, size, 0))
    return (buf, got) if 0 < got <= size else None


def _load_seq_state(llm, saved, tokens) -> bool:
    """Put a saved memory back and tell llama-cpp-python which tokens it holds."""
    from llama_cpp import llama_cpp as _lc
    buf, got = saved
    llm._ctx.kv_cache_clear()
    if int(_lc.llama_state_seq_set_data(llm._ctx.ctx, buf, got, 0)) != got:
        llm.reset()
        llm._ctx.kv_cache_clear()
        return False
    llm.n_tokens = len(tokens)
    llm._input_ids[: len(tokens)] = tokens
    return True


def _resume_from_saved_state(llm, full_prompt: str, *, create: bool) -> str:
    """Before a call: put back the saved state for this prompt's fixed part, or read that part
    alone and save the state there. What follows is then all the model reads. Returns what was
    done ("restored", "saved", "") for the timing log. Any failure leaves an ordinary full read."""
    if os.environ.get("ELI_PROMPT_STATE_REUSE", "1").strip().lower() in ("0", "false", "no", "off"):
        return ""
    fixed = _stable_prefix_var.get()
    if not fixed or not full_prompt.startswith(fixed) or len(fixed) >= len(full_prompt):
        return ""
    try:
        prefix = llm.tokenize(fixed.encode("utf-8"), add_bos=True, special=True)
        whole = llm.tokenize(full_prompt.encode("utf-8"), add_bos=True, special=True)
        n = 0
        for a, b in zip(prefix, whole):
            if a != b:
                break
            n += 1
        # Worth it only past one batch: below that the fixed part is read in one step anyway.
        if n < max(1, int(getattr(llm, "n_batch", 0) or 0)) or n >= len(whole):
            return ""
        prefix = whole[:n]
        key = (id(llm), n, hash(tuple(prefix)))
        entry = _SAVED_STATES.get(key)
        if entry is not None and entry["llm"]() is llm and entry["tokens"] == prefix:
            if _load_seq_state(llm, entry["state"], prefix):
                _SAVED_STATES.move_to_end(key)
                return "restored"
            _SAVED_STATES.pop(key, None)
            return ""
        if not create:
            return ""
        # Read the fixed part alone. An attention cache that already holds it is cut back to it
        # instead; a running state cannot be cut back and is read again.
        held = list(llm._input_ids[: llm.n_tokens]) if llm.n_tokens else []
        if held[:n] == prefix and llm._ctx.kv_cache_seq_rm(-1, n, -1):
            llm.n_tokens = n
        else:
            llm.reset()
            llm._ctx.kv_cache_clear()
            llm.eval(prefix)
        state = _save_seq_state(llm)
        if state is None:
            return ""
        size = int(state[1])
        # No more than two contexts' worth of state either: "available" memory counts the file cache
        # a model's weights are mapped from, and a 35B's experts can be most of it.
        try:
            n_ctx = int(llm.n_ctx())
        except Exception:
            n_ctx = 0
        room = _saved_states_room()
        if n_ctx > 0:
            room = min(room, int(2 * n_ctx * size / max(1, n)))
        if size > room:
            return ""
        while _SAVED_STATES and sum(int(e["state"][1]) for e in _SAVED_STATES.values()) + size > room:
            _SAVED_STATES.popitem(last=False)
        import weakref
        _SAVED_STATES[key] = {"llm": weakref.ref(llm), "tokens": prefix, "state": state}
        return "saved"
    except Exception:
        _SWLOG.debug("saved model state not used", exc_info=True)
        try:
            llm.reset()
            llm._ctx.kv_cache_clear()
        except Exception:
            _SWLOG.debug("suppressed exception", exc_info=True)
        return ""


def _safe_invoke_llm(llm, full_prompt: str, *, temperature, max_tokens, top_p, top_k, repeat_penalty, stop, stream, grammar):
    """
    Invoke llama.cpp safely:
    - serialize calls via _LLM_CALL_LOCK
    - if requested tokens exceed context window, retry with smaller max_tokens
    """
    # Fit the request to the window before calling, not after it throws. Every generation passes
    # here, so a budget can't be bypassed (streaming used to pass max_tokens straight through and
    # overflowed a 4096 window). The retry below covers what an estimate can't predict.
    _fit_prompt, attempt_max = _fit_generation_budget(llm, full_prompt, max_tokens)
    if _fit_prompt is not full_prompt:
        full_prompt = _fit_prompt
    last_exc = None
    bg = is_background_inference()
    if not bg:
        # On the turn's audit row: how many times the model ran and how much it was given to read.
        try:
            from eli.kernel.request_context import turn_facts_var as _turn_facts
            _facts = _turn_facts.get()
            if _facts is not None:
                _facts["model_calls"] = int(_facts.get("model_calls") or 0) + 1
                _facts["prompt_chars"] = int(_facts.get("prompt_chars") or 0) + len(full_prompt or "")
        except Exception:
            _SWLOG.debug("suppressed exception", exc_info=True)
    if bg:
        # Background work does not start while a conversation is live or has just finished: it would take the
        # single model the next message needs, and prompt evaluation cannot be interrupted once begun.
        try:
            from eli.cognition.inference_broker import foreground_recently_active
            if float(os.environ.get("ELI_BG_DEFER_WINDOW", "30")) > 0 and foreground_recently_active(
                    float(os.environ.get("ELI_BG_DEFER_WINDOW", "30"))):
                return iter(()) if stream else {"choices": [{"text": ""}]}
        except Exception:
            _SWLOG.debug("background deferral check failed", exc_info=True)
    # Every generation carries a cooperative abort: it yields at the next token when
    # shutdown is signalled (so teardown never blocks on a long native call) and, for
    # background work, when a foreground turn announces priority on the shared lock.
    extra = {}
    _sc = _make_stopping_criteria(bg)
    if _sc is not None:
        extra["stopping_criteria"] = _sc

    _fg_started = [0.0]   # set while this call counts as a user-facing generation in progress

    def _acquire_lock_fg_priority():
        if not bg:
            try:
                from eli.cognition.inference_broker import foreground_call_started
                if not _fg_started[0]:
                    _fg_started[0] = foreground_call_started()
            except Exception:
                _SWLOG.debug("suppressed exception", exc_info=True)
            if _fg_preempt_enabled():
                _FG_PRIORITY.set()
        try:
            _LLM_CALL_LOCK.acquire()
        finally:
            if not bg and _fg_preempt_enabled():
                _FG_PRIORITY.clear()

    def _safe_release():
        # Release the call lock, tolerating "already released". A reload/abort race can release it
        # out from under this call, and the second release() used to kill the reply mid-stream.
        # Swallow exactly that case.
        try:
            _LLM_CALL_LOCK.release()
        except RuntimeError:
            _SWLOG.debug("suppressed exception", exc_info=True)
        if _fg_started[0]:
            try:
                from eli.cognition.inference_broker import foreground_call_finished
                foreground_call_finished(_fg_started[0])
                from eli.kernel.request_context import turn_facts_var as _turn_facts
                _facts = _turn_facts.get()
                if _facts is not None:
                    _facts["model_seconds"] = float(_facts.get("model_seconds") or 0.0) + max(
                        0.0, time.monotonic() - _fg_started[0])
            except Exception:
                _SWLOG.debug("suppressed exception", exc_info=True)
            _fg_started[0] = 0.0

    def _resume():
        _how = _resume_from_saved_state(llm, full_prompt, create=not bg)
        if _how:
            log.debug(f"[GGUF][STATE] {_how} the model state for the prompt's fixed part")

    for _ in range(4):
        try:
            if stream:
                _acquire_lock_fg_priority()
                try:
                    _resume()
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
                    _safe_release()
                    raise

                def _locked_stream():
                    try:
                        for item in response:
                            yield item
                    finally:
                        _safe_release()

                return _locked_stream()

            _acquire_lock_fg_priority()
            try:
                _resume()
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
                _safe_release()
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            if "exceed context window" in msg or "requested tokens" in msg:
                # Two overflow shapes: (a) max_tokens too big for the remaining window, (b) the
                # prompt alone exceeds it. Halving max_tokens only fixes (a); for (b) shrink the
                # prompt (head+tail, once) or the retries run out.
                _lim = _effective_ctx_limit(llm)
                _ptok = _estimate_prompt_tokens(llm, full_prompt)
                _gen_floor = max(64, min(256, _lim // 8))
                if _ptok > _lim - _gen_floor:
                    full_prompt = _truncate_prompt_to_tokens(llm, full_prompt, max(256, _lim - _gen_floor))
                    _ptok2 = _estimate_prompt_tokens(llm, full_prompt)
                    attempt_max = max(64, min(attempt_max, _lim - _ptok2 - 16))
                    log.debug(f"[GGUF] Context-window retry: prompt {_ptok}>{_lim} tok; "
                              f"truncated head+tail to {_ptok2} tok, max_tokens={attempt_max}")
                    continue
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
        _SWLOG.debug("suppressed exception", exc_info=True)
    # char-based fallback (~4 chars/token)
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    half = max(1, max_chars // 2)
    return text[:half] + "\n…\n" + text[-half:]


def _model_train_ctx(model_path=None) -> int:
    """The model's real trained context (`n_ctx_train`), read from GGUF metadata.

    This is the HARD ceiling for prompt+generation, independent of how large a context
    the loader actually requested: a 4096-train model loaded at 16384 ("training context
    overflow") still cannot attend past 4096, so sizing must use 4096. Returns 0 when the
    model/metadata is unknown. Model-agnostic — driven by metadata, not the filename.
    """
    try:
        from eli.core.startup_hardware_optimizer import train_ctx_for_model as _tc
        mp = model_path or get_model_path()
        if mp:
            v = int(_tc(str(mp)))
            return v if v > 0 else 0
    except Exception:
        _SWLOG.debug("suppressed exception", exc_info=True)
    return 0


def _effective_ctx_limit(llm) -> int:
    """Usable context ceiling = min(loaded n_ctx, n_ctx_train).

    The loaded n_ctx can exceed the model's trained length (the adaptive fallback loader
    or a stale config can request more); the model still only attends n_ctx_train. Sizing
    and truncation must use the SMALLER of the two so an over-ctx load never fools the
    "does the prompt fit?" math into skipping truncation (which produced
    'Requested tokens exceed context window' / garbled output on the 4k phi-3).
    """
    loaded = _loaded_ctx(llm)
    train = _model_train_ctx()
    # Cross-check the ctx load_model() recorded, the authoritative record of what this llm was built
    # with. llm.n_ctx() returned a stale larger figure after a smart-fit reload. A smaller snapshot
    # value is never overridden by a larger live read.
    snap_eff = 0
    try:
        _rep = globals().get("_ELI_EFFECTIVE_RUNTIME_REPORT") or {}
        snap_eff = int((_rep.get("effective") or {}).get("n_ctx") or 0)
    except Exception:
        snap_eff = 0
    candidates = [v for v in (loaded, train, snap_eff) if v > 0]
    return min(candidates) if candidates else 0


def _loaded_ctx(llm) -> int:
    """The context this llm object was built with, or 0 when it cannot say.

    Never the configured or requested value: that is what was asked for, and a fallback loads
    less. The GUI replaced llm.n_ctx with a plain number, the call failed, and the user's requested
    ctx sized every prompt for a model the fallback had loaded at a sixth of it."""
    for value in (getattr(llm, "n_ctx", None), getattr(llm, "_n_ctx", None),
                  getattr(getattr(llm, "context_params", None), "n_ctx", None)):
        try:
            value = int((value() if callable(value) else value) or 0)
        except Exception:
            continue
        if value > 0:
            return value
    return 0


def _ctx_max_tokens(llm, full_prompt: str, reserve: int = 128) -> int:
    """
    Return the maximum tokens the model can generate for this prompt:
        effective_ctx - prompt_tokens - reserve
    where effective_ctx = min(loaded n_ctx, n_ctx_train). Can be 0 when the prompt
    already exhausts context.
    """
    n_ctx = _effective_ctx_limit(llm)
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


def current_context_limit() -> int:
    """Public: usable context ceiling for the loaded model = min(loaded n_ctx,
    n_ctx_train). Returns 0 when no model is loaded. Callers that pre-size prompts
    (e.g. the engine's streaming preflight clamp) must use THIS, not the config
    default — the loaded ctx can exceed the model's trained attention window, and the
    config default can be stale-large; both fool a naive prompt-fit check."""
    llm = globals().get("_llm")
    if llm is None:
        return 0
    try:
        return int(_effective_ctx_limit(llm))
    except Exception:
        return 0


def context_window() -> int:
    """The context window every budget sizes against.

    Best known first: the model loaded in this process; the runtime published when one was loaded
    (by the GUI's own loader, or by another ELI process through runtime_snapshot.json, for the
    same model); the operator's setting; the auto context for the configured model on this
    machine. 0 when there is no model to size for. Never a constant: one fixed number is wrong
    for most of the models and machines ELI runs on."""
    live = current_context_limit()
    if live > 0:
        return live
    try:
        published = dict(globals().get("_live_runtime_params") or {})
        if published.get("loaded", True) and int(published.get("n_ctx") or 0) > 0:
            return int(published["n_ctx"])
    except Exception:
        _SWLOG.debug("published runtime unreadable", exc_info=True)
    try:
        from eli.core.paths import get_paths
        snap_path = Path(get_paths().artifacts_dir) / "runtime_snapshot.json"
        snap = json.loads(snap_path.read_text(encoding="utf-8")) if snap_path.is_file() else {}
        snap_ctx = int((snap.get("effective") or {}).get("n_ctx") or snap.get("n_ctx") or 0)
        snap_model = Path(str(snap.get("model_path") or "")).name
        configured = get_model_path()
        if snap_ctx > 0 and (not configured or not snap_model or snap_model == configured.name):
            return snap_ctx
    except Exception:
        _SWLOG.debug("runtime snapshot unreadable", exc_info=True)
    try:
        from eli.core import config as _cfg
        return max(0, int(_cfg.get_gguf_n_ctx()))
    except Exception:
        _SWLOG.debug("configured context unreadable", exc_info=True)
        return 0


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

    full_prompt = _prompt_for_call(system, prompt, structured=False, max_tokens=max_tokens)

    available_tokens = _ctx_max_tokens(llm, full_prompt)
    if available_tokens <= 0:
        # The prompt alone exceeds the window (a big model crushed to a small ctx). Truncate
        # head+tail to fit and reserve a minimum generation budget instead of failing the turn. Head
        # keeps the system/persona, tail keeps the recent context and the user turn.
        _n_ctx = _effective_ctx_limit(llm)
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

    fam = _resolve_family_for_loaded(path=get_model_path())
    _mp = get_model_path()

    try:
        from eli.cognition.model_output_tokens import stop_tokens_for_family
        stop += stop_tokens_for_family(
            fam,
            include_label_stops=not _is_thinking_model(),
        )
    except Exception:
        # Fallback: legacy universal stops if import fails
        stop += ["<|im_start|>", "<|im_end|>",
                 "<|user|>", "<|assistant|>", "<|system|>"]
        if not _is_thinking_model():
            stop += [
                "User:", "USER:", "\nUser:", "\nUSER:", "\n\nUser:", "\n\nUSER:",
                "Assistant:", "ASSISTANT:", "\nAssistant:", "\nASSISTANT:",
                "\n\nAssistant:", "\n\nASSISTANT:",
            ]
        if _is_mistral_model(_mp):
            stop += ["</s>", "[INST]", "[/INST]"]
        elif _is_llama_model(_mp):
            stop += ["<|eot_id|>", "<|end_of_text|>", "<|start_header_id|>"]
        else:
            stop += ["<|end|>", "<|eot_id|>"]
        if _is_chatml_model(_mp):
            stop += ["<|im_end|>"]
    # the end of the model's turn as its own template writes it
    from eli.cognition.chat_template import stop_markers
    stop += stop_markers()

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
        _streamed_any = False
        for chunk in _stream_clean_chunks(_strip_think_stream(
                {"response": c["choices"][0]["text"]} for c in response)):
            cleaned = chunk.get("response", "")
            if cleaned:
                _streamed_any = True
                yield {"response": cleaned}
        # A reasoning model can spend its whole budget inside <think> → the stream strips to
        # nothing → dead turn. (The broker handles this for non-stream calls; the streaming
        # main-answer path doesn't go through it.) Retry ONCE forcing no-think so it answers.
        if (not _streamed_any) and (not _force_no_think_active()) and grammar is None:
            # Retry even when the name heuristic missed a thinking model (TwIL /
            # SmolLM3 thought for 35s with zero visible tokens because
            # `_is_thinking_model` only knew Qwen3/R1 names).
            log.debug("[GGUF] empty stream — one no-think retry")
            try:
                with force_no_think():
                    _rp = _prompt_for_call(system, prompt, structured=False, max_tokens=max_tokens)
                    _r = _safe_invoke_llm(
                        llm, _rp, temperature=temperature, max_tokens=min(int(max_tokens or 512), 512),
                        top_p=top_p, top_k=top_k, repeat_penalty=repeat_penalty, stop=stop,
                        stream=False, grammar=None)
                    _c = _clean_eli_output(_r["choices"][0]["text"])
                    if _c.strip():
                        yield {"response": _c}
            except Exception:
                log.debug("[GGUF] stream no-think retry failed", exc_info=True)
        log.debug(f"[GGUF][TIMING] stream_call_total={time.perf_counter()-started:.3f}s")
        _note_headroom()
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
        _note_headroom()
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
            _SWLOG.debug("suppressed exception", exc_info=True)
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
    _full_prompt = _prompt_for_call(system, prompt, structured=True, max_tokens=max_tokens)
    _available_tokens = _ctx_max_tokens(llm, _full_prompt)
    if _available_tokens <= 0:
        # Truncate head+tail to fit rather than fail the call (same as the chat path).
        _n_ctx = _effective_ctx_limit(llm)
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
        forget_saved_states()
        if _llm is not None:
            try:
                _llm.close()
            except Exception:
                _SWLOG.debug("suppressed exception", exc_info=True)
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
        # Settings save writes model_path, but get_model_path() prefers ELI_GGUF_MODEL_PATH, which
        # the GUI pins to the previous model. Re-publish the env from the saved settings before
        # load_model() or a swap reloads the same GGUF forever.
        try:
            from eli.core.runtime_settings import (
                load_settings_from_disk as _rs_disk,
                apply_env as _rs_apply_env,
            )
            _disk = _rs_disk()
            _prev_path = str(
                (globals().get("_live_runtime_params") or {}).get("model_path")
                or (globals().get("_live_runtime_override") or {}).get("model_path")
                or os.environ.get("ELI_GGUF_MODEL_PATH")
                or ""
            )
            _rs_apply_env(_disk)
            _new_path = str(
                (_disk or {}).get("model_path")
                or (_disk or {}).get("custom_model_path")
                or (_disk or {}).get("bundled_model_path")
                or ""
            ).strip()
            # Different weights → drop last-known-good ctx/gpu (sized for the old file).
            if _new_path and _prev_path:
                from eli.core.paths import resolve_runtime_path as _rrp
                try:
                    if _rrp(_new_path).resolve() != _rrp(_prev_path).resolve():
                        clear_live_runtime_override()
                except Exception:
                    clear_live_runtime_override()
        except Exception:
            log.debug("[GGUF] reload env sync skipped", exc_info=True)

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
    """Parameters the model was last loaded with.

    `_last_params` was declared at module level and never assigned, so this
    returned {} after every successful load and callers read None for every
    field. The load path does populate `_live_runtime_params`, so fall back to
    it rather than reporting nothing about a model that is demonstrably
    loaded.
    """
    if _last_params:
        return dict(_last_params)
    live = globals().get("_live_runtime_params") or {}
    return dict(live)


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
            _SWLOG.debug("suppressed exception", exc_info=True)


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
        _SWLOG.debug("suppressed exception", exc_info=True)
    return dict(clean)

def clear_runtime_override() -> None:
    globals().pop("_live_runtime_override", None)

def get_effective_runtime_report() -> Dict[str, Any]:
    """What the loaded model was asked for and loaded with; the snapshot below when nothing loaded here."""
    return dict(_ELI_EFFECTIVE_RUNTIME_REPORT) if _ELI_EFFECTIVE_RUNTIME_REPORT else get_runtime_snapshot()


def get_runtime_snapshot() -> Dict[str, Any]:
    if _ELI_EFFECTIVE_RUNTIME_REPORT and _llm is not None:
        return dict(_ELI_EFFECTIVE_RUNTIME_REPORT)
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
        _SWLOG.debug("suppressed exception", exc_info=True)

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
            snap["n_batch"] = int(_runtime_value(settings, "batch_size", "n_batch", default=0) or 0)
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
        _SWLOG.debug("suppressed exception", exc_info=True)

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
        _SWLOG.debug("suppressed exception", exc_info=True)
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


def _stream_chunk_text(tok) -> str:
    """Text of one streamed chunk, whatever shape it arrives in.

    The legacy generator yields dicts -- {"response": "..."} -- not strings.
    The buffer only appended `isinstance(tok, str)`, so every dict contributed
    nothing and str() of a stream that had really produced text came back
    empty: `generate("Say hello")` logged RAW_TEXT 'Hello! How can I help you
    today' and stringified to ''. Silently returning nothing for a call that
    succeeded is the same failure class as the generator-repr leak this class
    was written to stop.
    """
    if isinstance(tok, str):
        return tok
    if isinstance(tok, dict):
        for key in ("response", "text", "content", "delta"):
            val = tok.get(key)
            if isinstance(val, str) and val:
                return val
        # OpenAI-shaped: {"choices": [{"text": ...}]}
        try:
            choice = (tok.get("choices") or [{}])[0]
            for key in ("text", "content"):
                val = choice.get(key)
                if isinstance(val, str) and val:
                    return val
            delta = choice.get("delta") or {}
            val = delta.get("content")
            if isinstance(val, str) and val:
                return val
        except Exception:
            log.debug("stream chunk shape not recognised", exc_info=True)
    return ""


class _CleanTokenStream:
    """Iterator over cleaned streaming tokens whose ``str()``/``repr()`` NEVER
    expose the default ``<generator object ...>`` text.

    A streaming reply is meant to be *iterated*. Several hops in the engine
    (`_stream_model_response` → `generate_stream_from_assembled_prompt` →
    `_stream_chat`) defensively do ``str(chunk or "")`` on whatever they receive.
    When a bare generator slipped through one of those hops it was stringified
    into ``<generator object _wrap_stream_or_text.<locals>.gen at 0x…>`` and that
    literal repr was shown as ELI's reply (observed on the embedder-missing
    keyword-fallback path). Making the wrapper a real iterator with a text
    ``__str__`` closes that at the single chokepoint: iterate → tokens as before;
    accidental ``str()`` → the actual reply text (draining what remains), never a
    repr. Tokens are buffered as they stream so ``str()`` after partial iteration
    still returns everything seen. No logging path stringifies this object, so
    draining-on-str cannot pre-consume a live stream.
    """

    __slots__ = ("_it", "_buf")

    def __init__(self, it):
        self._it = iter(it)
        self._buf: list[str] = []

    def __iter__(self):
        return self

    def __next__(self):
        tok = next(self._it)
        self._buf.append(_stream_chunk_text(tok))
        return tok

    def _drain(self) -> str:
        for tok in self._it:
            self._buf.append(_stream_chunk_text(tok))
        return "".join(self._buf)

    def __str__(self) -> str:
        return self._drain()

    __repr__ = __str__


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
        return _CleanTokenStream(gen())

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
