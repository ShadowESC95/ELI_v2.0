from __future__ import annotations

import inspect
import json
import platform
import re
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _runtime_snapshot() -> dict[str, Any]:
    snap = PROJECT_ROOT / "artifacts" / "runtime_snapshot.json"
    if snap.exists():
        try:
            return json.loads(snap.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _settings() -> dict[str, Any]:
    cfg = PROJECT_ROOT / "config" / "settings.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _gpu_line() -> str:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used,memory.free,driver_version",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=2,
        ).strip().splitlines()
        return out[0].strip() if out else "unavailable"
    except Exception:
        return "unavailable"


def _mode_is_quick(mode: Any) -> bool:
    s = str(mode or "").lower()
    return s in {"quick", "quick_mode", "⚡ quick"} or "quick" in s


def _runtime_question(text: Any) -> bool:
    low = str(text or "").lower()
    return (
        "what are you actually running" in low
        or ("model" in low and "context" in low and "gpu" in low)
        or ("runtime" in low and "gpu" in low)
    )


def _plain_identity_question(text: Any) -> bool:
    low = str(text or "").lower().strip()
    return bool(re.search(r"\bwho are you\b", low)) and not _runtime_question(low)


def _name_source_question(text: Any) -> bool:
    low = str(text or "").lower()
    return "name" in low and ("how do you know" in low or "which file" in low or "where" in low)


def format_runtime_truth(mode: Any = "") -> str:
    settings = _settings()
    snap = _runtime_snapshot()

    provider = settings.get("provider") or "custom_gguf"
    model = (
        snap.get("model_path")
        or settings.get("model_path")
        or settings.get("gguf_model_path")
        or "unknown"
    )
    model = str(model).replace(str(PROJECT_ROOT) + "/", "")

    effective_ctx = snap.get("n_ctx") or snap.get("ctx") or "unknown"
    effective_gpu = snap.get("n_gpu_layers") or snap.get("gpu_layers") or "unknown"
    effective_threads = snap.get("n_threads") or settings.get("n_threads") or "unknown"
    effective_batch = snap.get("n_batch") or snap.get("batch_size") or settings.get("batch_size") or "unknown"

    return json.dumps(
        {
            "surface": "runtime_truth_evidence",
            "provider": provider,
            "model_path": model,
            "effective": {
                "n_ctx": effective_ctx,
                "n_gpu_layers": effective_gpu,
                "n_threads": effective_threads,
                "n_batch": effective_batch,
                "gpu": _gpu_line(),
            },
            "configured": {
                "n_ctx": settings.get("n_ctx", "unknown"),
                "n_gpu_layers": settings.get("n_gpu_layers", settings.get("gpu_layers", "unknown")),
                "n_threads": settings.get("n_threads", "unknown"),
                "batch_size": settings.get("batch_size", "unknown"),
                "max_tokens": settings.get("max_tokens", "unknown"),
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def format_identity(mode: Any = "") -> str:
    persona_paths = [
        PROJECT_ROOT / "eli" / "cognition" / "persona.txt",
        PROJECT_ROOT / "eli" / "cognition" / "persona.auto.txt",
    ]
    evidence = []
    for path in persona_paths:
        try:
            if path.exists():
                evidence.append({"path": str(path), "chars": len(path.read_text(encoding="utf-8", errors="replace"))})
        except Exception as exc:
            evidence.append({"path": str(path), "error": repr(exc)})
    return json.dumps(
        {
            "surface": "identity_evidence",
            "identity_name": "ELI",
            "evidence_sources": evidence,
            "runtime_snapshot": bool(_runtime_snapshot()),
            "settings": bool(_settings()),
        },
        ensure_ascii=False,
        indent=2,
    )


def format_name_source_audit(text: Any = "") -> str:
    return json.dumps(
        {
            "surface": "name_source_evidence",
            "allowed_sources": [
                "SQLite memory rows",
                "conversation rows",
                "settings fields",
                "profile artifacts",
                "imported or quarantined memory",
            ],
            "question": str(text or ""),
        },
        ensure_ascii=False,
        indent=2,
    )


def _consume_generator(gen: Any) -> str:
    parts: list[str] = []
    try:
        for chunk in gen:
            if chunk is None:
                continue
            if isinstance(chunk, str):
                parts.append(chunk)
            elif isinstance(chunk, dict):
                val = (
                    chunk.get("response")
                    or chunk.get("content")
                    or chunk.get("text")
                    or chunk.get("delta")
                    or chunk.get("message")
                )
                if val:
                    parts.append(str(val))
            else:
                parts.append(str(chunk))
    except Exception as e:
        parts.append(f"[stream failed: {type(e).__name__}: {e}]")
    return "".join(parts).strip()


def coerce_user_visible(result: Any, user_input: Any = "", mode: Any = "") -> str:
    # Prevent <generator object ...> from ever reaching the GUI.
    if inspect.isgenerator(result) or inspect.isasyncgen(result):
        return _consume_generator(result)

    if isinstance(result, str):
        _s = result.strip()
        if (
            (_s.startswith("{") or _s.startswith("["))
            and (
                '"surface":' in _s[:800]
                or "memory_truth_evidence" in _s[:800]
                or "runtime_truth_evidence" in _s[:800]
                or "missing_user_visible_text" in _s[:800]
            )
        ):
            # Runtime truth/status evidence is already user-facing.
            # Do not collapse it into the generic diagnostic fallback.
            try:
                _raw_surface_text = str(_s or "")
            except Exception:
                _raw_surface_text = ""
            _raw_surface_head = _raw_surface_text[:1200]
            if (
                "runtime_truth_evidence" in _raw_surface_head
                or _raw_surface_text.lstrip().startswith("Runtime status")
                or _raw_surface_text.lstrip().startswith("Runtime truth report")
            ):
                return _raw_surface_text
            return "A diagnostic evidence packet was produced, but it is not a user-facing answer."
        return result

    if isinstance(result, dict):
        action = str(result.get("action") or "").upper()

        # Prefer a clean response/content field.
        for key in ("response", "content", "message", "text"):
            val = result.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

        # Last-resort: never surface a raw envelope to the user.
        return f"No user-visible response was produced for action {action or 'UNKNOWN'}."

    if result is None:
        return ""

    return str(result)


def _coerce_streaming_result(result: Any, user_input: Any = "", mode: Any = "") -> Any:
    """
    Stream-aware coercer.
    - Generators / async generators: pass through, but ensure each yielded chunk
      is converted to a clean string (no dict reprs, no envelope leakage).
    - Dicts / strings / None: collapse to the user-visible string via
      coerce_user_visible() and return that string directly.
    """
    if inspect.isgenerator(result) or inspect.isasyncgen(result):
        def _safe_chunks():
            try:
                for chunk in result:
                    if chunk is None:
                        continue
                    if isinstance(chunk, str):
                        if chunk:
                            yield chunk
                        continue
                    if isinstance(chunk, dict):
                        text = ""
                        for key in ("response", "content", "message", "text", "delta"):
                            val = chunk.get(key)
                            if isinstance(val, str) and val.strip():
                                text = val.strip()
                                break
                        if text:
                            yield text
                        # Silently drop any envelope chunk with no usable text.
                        continue
                    yield str(chunk)
            except Exception as e:
                yield f"[stream failed: {type(e).__name__}: {e}]"
        return _safe_chunks()
    return coerce_user_visible(result, user_input=user_input, mode=mode)


def install_engine_response_surface(CognitiveEngine: Any) -> None:
    """
    Deprecated no-op.

    The global CognitiveEngine.process response-surface wrapper has been retired.
    User-visible coercion now belongs at consumer boundaries, using
    eli.runtime.visible_text.to_user_visible_text().

    This function remains only as a compatibility shim for older imports.
    It must not mutate CognitiveEngine.process.
    """
    return None
