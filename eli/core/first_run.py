from __future__ import annotations

from typing import Any, Dict

from eli.core import runtime_settings


def is_first_run_complete() -> bool:
    settings = runtime_settings.load_settings()
    return bool(settings.get("first_run_complete", False))


def first_run_status() -> Dict[str, Any]:
    settings = runtime_settings.load_settings()
    model_path = (
        settings.get("model_path")
        or settings.get("custom_model_path")
        or settings.get("bundled_model_path")
        or ""
    )
    return {
        "ok": True,
        "first_run_complete": bool(settings.get("first_run_complete", False)),
        "provider": settings.get("provider"),
        "model_path": model_path,
        "n_ctx": settings.get("n_ctx"),
        "n_gpu_layers": settings.get("n_gpu_layers"),
        "n_threads": settings.get("n_threads"),
        "batch_size": settings.get("batch_size"),
    }


def mark_first_run_complete(value: bool = True) -> Dict[str, Any]:
    runtime_settings.update_settings(first_run_complete=bool(value))
    return first_run_status()


__all__ = [
    "first_run_status",
    "is_first_run_complete",
    "mark_first_run_complete",
]
