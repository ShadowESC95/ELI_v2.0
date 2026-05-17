"""
eli.tools/chat_model.py (MKV)

Authoritative chat interface for ELI.

Guarantees:
- Builds system context via brain.context_builder.build_context()
- Calls Ollama via HTTP /api/chat (works with or without python 'ollama' module)
- Persists structured turns to SQLite via _eli_path_get(brain, "memory_db").add_memory
- Never lies about capabilities: system context includes persona + truth policy + (optional) capabilities

Env:
- ELI_CHAT_MODEL / ELI_MODEL / OLLAMA_MODEL
- OLLAMA_HOST / ELI_OLLAMA_HOST  (default http://localhost:11434)
- ELI_TEMP (default 0.7)
- ELI_NUM_PREDICT (default 4000)
- ELI_STREAM_DEBUG=1   (prints stream parsing hints)
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Union
import os
import json
import time

from eli.cognition.context_builder import build_context
from eli.memory import add_memory, log_event

def _eli_path_get(obj, key, default=None):
    """
    Compatibility helper for ELI path containers.
    Accepts both dict-style path maps and object/namespace-style path maps.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ----------------------------
# Model / host resolution
# ----------------------------

DEFAULT_MODEL = (
    os.environ.get("ELI_CHAT_MODEL")
    or os.environ.get("ELI_MODEL")
    or os.environ.get("OLLAMA_MODEL")
    or "eli-persona:latest"
)

DEFAULT_HOST = (
    os.environ.get("ELI_OLLAMA_HOST")
    or os.environ.get("OLLAMA_HOST")
    or "http://localhost:11434"
).rstrip("/")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _dbg_enabled() -> bool:
    return os.environ.get("ELI_STREAM_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_tags(tags: Union[str, List[str], None]) -> Union[str, List[str], None]:
    """
    Your project has had multiple memory adapters. Some want "a,b,c" strings,
    others want ["a","b","c"]. This keeps compatibility without touching memory_db.
    """
    if tags is None:
        return None
    if isinstance(tags, list):
        return tags
    if isinstance(tags, str):
        s = tags.strip()
        if not s:
            return ""
        # Keep as string by default (matches your current calls).
        return s
    return None


def _persist_turns(user_text: str, assistant_text: str, *, model: str) -> None:
    """
    Persist a user/assistant pair to SQLite. Best-effort: never crash chat.
    We store minimal structured tagging so later retrieval is sane.
    """
    try:
        add_memory(f"USER: {user_text}", tags=_normalize_tags("chat,user"))
    except Exception:
        pass

    try:
        add_memory(f"ASSISTANT: {assistant_text}", tags=_normalize_tags("chat,assistant"))
    except Exception:
        pass

    # Optional metadata breadcrumb
    try:
        # Some variants use log_event(name, **kwargs); others may not exist.
        log_event("chat_turn", {"model": model})
    except Exception:
        pass


# ----------------------------
# HTTP (requests) backend
# ----------------------------

def _requests_post_stream(url: str, payload: Dict[str, Any], timeout: int = 600) -> Iterator[Dict[str, Any]]:
    """
    Yield parsed JSON objects from Ollama NDJSON stream.
    """
    import requests  # installed in your venv

    with requests.post(url, json=payload, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except Exception:
                if _dbg_enabled():
                    print(f"[eli.chat_model] bad_json_line: {raw[:120]!r}")
                continue


def _requests_post_json(url: str, payload: Dict[str, Any], timeout: int = 600) -> Dict[str, Any]:
    import requests  # installed in your venv
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ----------------------------
# Public API
# ----------------------------

def chat_response(user: str, *, model: Optional[str] = None, host: Optional[str] = None, system: Optional[str] = None) -> str:
    """
    Non-streaming response (single final string).
    """
    mdl = (model or DEFAULT_MODEL).strip()
    h = (host or DEFAULT_HOST).rstrip("/")

    base_system = build_context(user)
    if system:
        system = (str(system).strip() + "\n\n" + str(base_system).strip()).strip()
    else:
        system = base_system

    payload: Dict[str, Any] = {
        "model": mdl,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": _env_float("ELI_TEMP", 0.7),
            "num_predict": _env_int("ELI_NUM_PREDICT", 4000),
        },
    }

    try:
        j = _requests_post_json(f"{h}/api/chat", payload, timeout=600)
        out = (j.get("message") or {}).get("content") or ""
    except Exception as e:
        out = f"Ollama unavailable or /api/chat failed: {e}"

    try:
        from eli.runtime.visible_output import visible_text as _eli_visible_text
        out = _eli_visible_text(out, user_input=user)
    except Exception:
        pass

    _persist_turns(user, out, model=mdl)
    return out


def chat_stream(
    messages: List[Dict[str, str]],
    *,
    model: Optional[str] = None,
    host: Optional[str] = None,
    timeout: int = 600,
) -> Iterator[str]:
    """
    Yield token-ish chunks from Ollama /api/chat (NDJSON streaming).

    IMPORTANT:
    - Some Ollama builds/models emit incremental deltas in message.content.
    - Others emit cumulative message.content (grows each event).
    To guarantee true streaming, we diff against previously seen text and yield only the delta.
    """
    mdl = (model or DEFAULT_MODEL).strip()
    h = (host or DEFAULT_HOST).rstrip("/")
    url = f"{h}/api/chat"

    payload: Dict[str, Any] = {
        "model": mdl,
        "stream": True,
        "messages": messages,
        "options": {
            "temperature": _env_float("ELI_TEMP", 0.7),
            "num_predict": _env_int("ELI_NUM_PREDICT", 4000),
        },
    }

    seen_text = ""
    last_yield_ts = time.time()

    for j in _requests_post_stream(url, payload, timeout=timeout):
        # done flag can appear at the end
        if j.get("done") is True:
            break

        msg = j.get("message") or {}
        content = msg.get("content")

        if not content:
            continue

        # Some streams provide incremental chunks; others provide cumulative content.
        # We always yield the delta.
        if content.startswith(seen_text):
            delta = content[len(seen_text):]
        else:
            # If the stream "resets" (rare), just yield what arrived.
            delta = content

        if delta:
            yield delta

            # Update seen_text to track "full content so far" regardless of mode.
            if content.startswith(seen_text):
                seen_text = content
            else:
                seen_text += delta

        if _dbg_enabled():
            now = time.time()
            if now - last_yield_ts > 2.0:
                print(f"[eli.chat_model] streaming... seen={len(seen_text)} chars")
                last_yield_ts = now


def chat_response_stream(
    user: str,
    *,
    model: Optional[str] = None,
    host: Optional[str] = None,
) -> Iterator[str]:
    """
    Streaming response for a single user prompt.
    Builds system context with build_context(user) and streams assistant output.
    Also persists turns to memory at the end (user + full assistant text).
    """
    mdl = (model or DEFAULT_MODEL).strip()
    h = (host or DEFAULT_HOST).rstrip("/")

    system = build_context(user)
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    full: List[str] = []
    for tok in chat_stream(messages, model=mdl, host=h):
        full.append(tok)
        yield tok

    out = "".join(full)
    _persist_turns(user, out, model=mdl)
