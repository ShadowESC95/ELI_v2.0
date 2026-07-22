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

DEFAULT_PORT = 11434
DEFAULT_HOST = f"http://127.0.0.1:{DEFAULT_PORT}"

_log = __import__("logging").getLogger("eli.ollama")


def normalise_host(raw: str) -> str:
    """Turn anything a user (or Ollama itself) might supply into a usable base URL.

    Ollama's own documentation and installers set ``OLLAMA_HOST`` **without a
    scheme** (``127.0.0.1:11434``, ``0.0.0.0:11434``), and users naturally type
    ``localhost:11434`` or a bare IP into the host box. urllib rejects all of
    those with "unknown url type", which silently broke Ollama on every OS for
    anyone who had followed Ollama's docs. Normalising in ONE place fixes the
    client, the startup picker, the wizard and the toolbar selector together.

        127.0.0.1:11434   -> http://127.0.0.1:11434
        localhost         -> http://localhost:11434
        192.168.1.5:11434 -> http://192.168.1.5:11434
        [::1]:11434       -> http://[::1]:11434
        https://box/      -> https://box:11434
    """
    h = str(raw or "").strip().rstrip("/")
    if not h:
        return DEFAULT_HOST
    if "://" not in h:
        h = "http://" + h
    scheme, _, rest = h.partition("://")
    if not rest:
        return DEFAULT_HOST
    # Split off any path, then decide whether a port is already present. IPv6
    # literals are bracketed, so only look for ':' after the closing bracket.
    hostport, slash, path = rest.partition("/")
    if hostport.startswith("["):
        has_port = "]:" in hostport
    else:
        has_port = ":" in hostport
    if not has_port:
        hostport = f"{hostport}:{DEFAULT_PORT}"
    return f"{scheme}://{hostport}" + (("/" + path) if slash and path else "")


def _host() -> str:
    """Resolve the Ollama base URL. Precedence: OLLAMA_HOST env → the user's
    configured ``ollama_host`` setting (so a non-default host/port set in the GUI
    is honoured everywhere, including the toolbar selector) → the local default."""
    env = os.environ.get("OLLAMA_HOST")
    if env:
        return normalise_host(env)
    try:
        from eli.core import config
        h = config.get("ollama_host")
        if h:
            return normalise_host(h)
    except Exception:
        _log.debug("ollama_host config read failed", exc_info=True)
    return DEFAULT_HOST


def candidate_hosts(host: Optional[str] = None) -> List[str]:
    """The base URLs to try, in order.

    ``localhost`` resolves to ``::1`` before ``127.0.0.1`` on many Windows and
    some Linux setups, while Ollama binds IPv4 by default — the classic symptom
    being a "connection refused" that looks like Ollama is down when it is
    running fine. Trying the IPv4 literal as a second candidate removes that
    whole class of report.
    """
    primary = normalise_host(host) if host else _host()
    out = [primary]
    scheme, _, rest = primary.partition("://")
    hostport, _, _ = rest.partition("/")
    name, _, port = hostport.rpartition(":")
    if name.lower() in ("localhost", "[::1]", "::1"):
        alt = f"{scheme}://127.0.0.1:{port or DEFAULT_PORT}"
        if alt not in out:
            out.append(alt)
    return out


_registered_hosts: set = set()


def _allow_via_netguard(base: str) -> None:
    """Let NetGuard reach a non-loopback Ollama.

    ELI is offline-by-default and only loopback is implicitly permitted, so a
    perfectly ordinary setup — Ollama on a desktop, ELI on a laptop — was blocked
    with no explanation. An Ollama endpoint the owner configured is a deliberate
    local service (same reasoning as the MQTT broker), so register it explicitly;
    the global policy is unchanged for every other host.
    """
    if base in _registered_hosts:
        return
    try:
        hostport = base.partition("://")[2].partition("/")[0]
        name = hostport.rsplit(":", 1)[0] if not hostport.startswith("[") \
            else hostport.partition("]")[0] + "]"
        from eli.core import netguard
        netguard.register_local_service(name)
        _registered_hosts.add(base)
    except Exception:
        _log.debug("netguard registration for %s failed", base, exc_info=True)


def install_hint() -> str:
    """Per-OS guidance for getting Ollama running (shown when it's unreachable)."""
    import sys
    if sys.platform == "darwin":
        return ("Install Ollama from https://ollama.com/download (or `brew install ollama`), "
                "then open the Ollama app — it runs in the menu bar. "
                "Pull a model with `ollama pull llama3.2`.")
    if sys.platform.startswith("win"):
        return ("Install Ollama from https://ollama.com/download — it starts automatically "
                "and lives in the system tray. If it isn't running, launch \"Ollama\" from "
                "the Start menu. Pull a model with `ollama pull llama3.2`.")
    return ("Install Ollama with `curl -fsSL https://ollama.com/install.sh | sh`, then start it "
            "with `systemctl --user start ollama` (or run `ollama serve`). "
            "Pull a model with `ollama pull llama3.2`.")


def _get(path: str, timeout: int = 10) -> Dict[str, Any]:
    last: Optional[Exception] = None
    bases = candidate_hosts()
    for base in bases:
        _allow_via_netguard(base)
        url = base + path
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="ignore"))
        except urllib.error.URLError as e:
            last = e            # try the next candidate (IPv6→IPv4 fallback)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Ollama returned invalid JSON from {path}: {e}") from e
    raise ConnectionError(f"Ollama unreachable at {bases[0]}: {last}") from last


def _post(path: str, payload: Dict[str, Any], timeout: int = 120) -> Dict[str, Any]:
    last: Optional[Exception] = None
    bases = candidate_hosts()
    body = json.dumps(payload).encode("utf-8")
    for base in bases:
        _allow_via_netguard(base)
        url = base + path
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
            # The server answered — a different candidate won't help.
            raw = ""
            try:
                raw = e.read().decode("utf-8", errors="ignore")
            except Exception:
                _log.debug("could not read Ollama error body", exc_info=True)
            raise RuntimeError(f"Ollama HTTP {e.code} on {path}: {raw[:300]}") from e
        except urllib.error.URLError as e:
            last = e            # unreachable — try the next candidate
    raise ConnectionError(f"Ollama unreachable at {bases[0]}: {last}") from last


def _delete(path: str, payload: Dict[str, Any], timeout: int = 30) -> bool:
    base = candidate_hosts()[0]
    _allow_via_netguard(base)
    url = base + path
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
    url = candidate_hosts()[0] + "/api/pull"
    _allow_via_netguard(candidate_hosts()[0])
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
        # `ollama serve` is Linux advice; Windows/macOS users need their own
        # instructions, and everyone needs to see WHICH host was actually tried.
        return (
            f"[Ollama is not reachable at {candidate_hosts()[0]}]\n"
            f"{install_hint()}\n"
            "If the host or port is different, set it in Settings > Model > Ollama. "
            "To use a local GGUF model instead, switch Backend there."
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
