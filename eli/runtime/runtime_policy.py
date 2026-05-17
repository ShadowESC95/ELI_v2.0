from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _snapshot() -> dict[str, Any]:
    path = _root() / "artifacts" / "runtime_snapshot.json"
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def context_size(default: int = 8192) -> int:
    snap = _snapshot()
    for key in ("n_ctx", "effective_context_size", "context_size"):
        try:
            value = int(snap.get(key) or 0)
            if value > 0:
                return value
        except Exception:
            pass
    try:
        return int(os.environ.get("ELI_CONTEXT_SIZE", str(default)) or default)
    except Exception:
        return int(default)


def budget(name: str, default: int, *, floor: int | None = None, ceiling: int | None = None) -> int:
    env_name = "ELI_BUDGET_" + str(name or "").upper()
    try:
        if os.environ.get(env_name):
            value = int(os.environ[env_name])
        else:
            ctx = context_size()
            scale = max(1.0, min(4.0, ctx / 8192.0))
            value = int(round(float(default) * scale))
    except Exception:
        value = int(default)
    if floor is not None:
        value = max(int(floor), value)
    if ceiling is not None:
        value = min(int(ceiling), value)
    return int(value)


def timeout(name: str, default: float) -> float:
    env_name = "ELI_TIMEOUT_" + str(name or "").upper()
    try:
        if os.environ.get(env_name):
            return max(0.1, float(os.environ[env_name]))
        ctx = context_size()
        if ctx >= 32768:
            return float(default) * 1.5
        if ctx >= 16384:
            return float(default) * 1.25
        return float(default)
    except Exception:
        return float(default)


def tts_chunk_chars(default: int = 360) -> int:
    try:
        return budget("tts_chunk_chars", default, floor=180, ceiling=900)
    except Exception:
        return int(default)
