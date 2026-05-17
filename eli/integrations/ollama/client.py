"""
Ollama client for ELI.

Features:
  - list_models()       → sorted list of installed models (for GUI dropdown)
  - chat_completion()   → matches GGUF's chat_completion() signature
  - pull_model()        → pull from Ollama registry (runs in thread for large models)
  - delete_model()      → remove a model
  - is_running()        → health check
  - get_model_info()    → metadata/parameters for a model
  - set_active_model()  → persist selected model to config
  - get_active_model()  → read persisted model from config

Config key: "ollama_model"  (stored in ELI's canonical config.json path)
Env override: OLLAMA_MODEL, ELI_CHAT_MODEL
Host override: OLLAMA_HOST (default: http://localhost:11434)
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Generator, List, Optional


# ──────────────────────────────────────────────────────────────
# Internal HTTP helpers (stdlib-only, no requests dependency)
# ──────────────────────────────────────────────────────────────

def _host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


def _get(path: str, timeout: int = 10) -> Dict[str, Any]:
    url = _host() + path
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except urllib.error.URLError as e:
        raise ConnectionError(f"Ollama unreachable at {url}: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Ollama returned invalid JSON from {path}: {e}") from e


def _post(path: str, payload: Dict[str, Any], timeout: int = 120) -> Dict[str, Any]:
    url = _host() + path
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        raise RuntimeError(f"Ollama HTTP {e.code} on {path}: {raw[:300]}") from e
    except urllib.error.URLError as e:
        raise ConnectionError(f"Ollama unreachable at {url}: {e}") from e


def _delete(path: str, payload: Dict[str, Any], timeout: int = 30) -> bool:
    url = _host() + path
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def is_running() -> bool:
    """Return True if Ollama is reachable."""
    try:
        _get("/api/version", timeout=3)
        return True
    except Exception:
        return False


def get_version() -> str:
    """Return Ollama version string, or 'unavailable'."""
    try:
        data = _get("/api/version", timeout=3)
        return data.get("version", "unknown")
    except Exception:
        return "unavailable"


def list_models() -> List[str]:
    """
    Return a sorted list of installed Ollama model names.
    Returns [] if Ollama is not running or no models installed.
    Safe to call at any time — never raises.
    """
    try:
        data = _get("/api/tags", timeout=5)
        models = data.get("models", [])
        return sorted(
            m["name"] for m in models
            if isinstance(m, dict) and "name" in m
        )
    except Exception:
        return []


def get_model_info(model: str) -> Dict[str, Any]:
    """Return metadata dict for a model (parameters, template, etc.)."""
    try:
        return _post("/api/show", {"name": model}, timeout=10)
    except Exception as e:
        return {"error": str(e), "model": model}


def set_active_model(model: str) -> None:
    """Persist model selection to ELI config."""
    try:
        from eli.core import config
        config.set("ollama_model", model)
    except Exception:
        pass


def get_active_model() -> Optional[str]:
    """
    Return the currently selected Ollama model.
    Resolution order: OLLAMA_MODEL env → ELI_CHAT_MODEL env → config → first installed → None
    """
    for env in ("OLLAMA_MODEL", "ELI_CHAT_MODEL"):
        v = os.environ.get(env)
        if v:
            return v

    try:
        from eli.core import config
        v = config.get("ollama_model")
        if v:
            return v
    except Exception:
        pass

    # Auto-select first installed model
    models = list_models()
    return models[0] if models else None


def pull_model(
    model: str,
    progress_cb: Optional[Callable[[str, int], None]] = None,
) -> Dict[str, Any]:
    """
    Pull a model from Ollama registry.
    progress_cb(status_str, percent_int) called during download.
    Runs synchronously — call in a thread for large models.
    Returns {"ok": True/False, "model": ..., "error": ...}
    """
    url = _host() + "/api/pull"
    body = json.dumps({"name": model, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            while True:
                line = resp.readline()
                if not line:
                    break
                try:
                    chunk = json.loads(line.decode("utf-8", errors="ignore"))
                except Exception:
                    continue
                status = chunk.get("status", "")
                total = chunk.get("total", 0)
                completed = chunk.get("completed", 0)
                pct = int(completed / total * 100) if total > 0 else 0
                if progress_cb:
                    progress_cb(status, pct)
                if chunk.get("status") == "success":
                    return {"ok": True, "model": model}
        return {"ok": True, "model": model}
    except Exception as e:
        return {"ok": False, "model": model, "error": str(e)}


def pull_model_async(
    model: str,
    progress_cb: Optional[Callable[[str, int], None]] = None,
    done_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> threading.Thread:
    """
    Pull a model in a background thread.
    Returns the Thread (already started).
    done_cb(result_dict) called when finished.
    """
    def _run():
        result = pull_model(model, progress_cb=progress_cb)
        if done_cb:
            done_cb(result)

    t = threading.Thread(target=_run, daemon=True, name=f"ollama-pull-{model}")
    t.start()
    return t


def delete_model(model: str) -> Dict[str, Any]:
    """Delete an installed model."""
    ok = _delete("/api/delete", {"name": model})
    return {"ok": ok, "model": model}


# ──────────────────────────────────────────────────────────────
# Chat completion (matches GGUF's chat_completion() signature)
# ──────────────────────────────────────────────────────────────

def chat(
    model: str,
    messages: List[Dict[str, str]],
    system: Optional[str] = None,
    temperature: float = 0.55,
    max_tokens: int = 2048,
    top_p: float = 0.9,
    top_k: int = 40,
    repeat_penalty: float = 1.15,
) -> str:
    """
    Low-level chat call. Returns the assistant response string.
    Raises RuntimeError / ConnectionError on failure.
    """
    if system:
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": system}] + list(messages)

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "top_p": top_p,
            "top_k": top_k,
            "repeat_penalty": repeat_penalty,
        },
    }

    data = _post("/api/chat", payload, timeout=180)
    msg = data.get("message", {})
    return (msg.get("content") or "").strip()


def chat_completion(
    prompt: str,
    system: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs,
) -> str:
    """
    High-level wrapper matching GGUF's chat_completion() signature.
    Falls back gracefully with an informative message if Ollama is not running.

    Accepted kwargs: temperature, max_tokens, num_predict, top_p, top_k, repeat_penalty
    """
    if not is_running():
        return (
            "[Ollama is not running. Start it with: ollama serve]\n"
            "If you want to use a local GGUF model instead, check your model config."
        )

    resolved_model = model or get_active_model()
    if not resolved_model:
        models = list_models()
        if not models:
            return "[No Ollama models installed. Pull one with: ollama pull llama3.2]"
        resolved_model = models[0]

    temperature = float(kwargs.get("temperature", 0.55))
    max_tokens = int(kwargs.get("max_tokens", kwargs.get("num_predict", 2048)))
    top_p = float(kwargs.get("top_p", 0.9))
    top_k = int(kwargs.get("top_k", 40))
    repeat_penalty = float(kwargs.get("repeat_penalty", 1.15))

    messages = [{"role": "user", "content": prompt}]

    try:
        return chat(
            model=resolved_model,
            messages=messages,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            top_k=top_k,
            repeat_penalty=repeat_penalty,
        )
    except ConnectionError:
        return "[Ollama connection lost during generation. Is 'ollama serve' still running?]"
    except RuntimeError as e:
        return f"[Ollama error: {e}]"
    except Exception as e:
        return f"[Unexpected Ollama error: {e}]"


# ──────────────────────────────────────────────────────────────
# Backward-compat: generate() matching GGUF's generate() API
# ──────────────────────────────────────────────────────────────

def generate(
    prompt: str,
    system: Optional[str] = None,
    stream: bool = False,
    **kwargs,
) -> Generator[Dict[str, str], None, None]:
    """Yield {"response": chunk} dicts — matches GGUF generate() signature."""
    response = chat_completion(prompt=prompt, system=system, **kwargs)
    yield {"response": response}
