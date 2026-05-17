from __future__ import annotations

import json
import time
from pathlib import Path
import os
from eli.core.paths import get_paths
from typing import Any, Dict


def _get_lock_path() -> Path:
    lock_dir = Path(os.environ.get("ELI_ARTIFACTS_DIR", "."))
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / "persona_lock.json"


def get_lock_state() -> Dict[str, Any]:
    lock_path = _get_lock_path()
    if not lock_path.exists():
        return {"locked": False, "expected_model": None}

    try:
        with open(lock_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"locked": False, "expected_model": None, "error": "invalid_lock_format"}
        return {
            "locked": bool(data.get("locked", False)),
            "expected_model": data.get("expected_model"),
            "timestamp": data.get("timestamp"),
        }
    except Exception as e:
        return {"locked": False, "expected_model": None, "error": str(e)}


def status() -> Dict[str, Any]:
    state = get_lock_state()
    return {
        "ok": True,
        "module": "identity_guard",
        "mode": "active",
        "locked": bool(state.get("locked", False)),
        "expected_model": state.get("expected_model"),
        "timestamp": state.get("timestamp"),
        "lock_path": str(_get_lock_path()),
    }


def clear_lock() -> bool:
    lock_path = _get_lock_path()
    if lock_path.exists():
        lock_path.unlink()

    try:
        from eli.runtime.authority_state import get_state
        state = get_state()
        if hasattr(state, "locked_model"):
            state.locked_model = None
        if hasattr(state, "persona_lock"):
            state.persona_lock = None
    except Exception:
        pass

    return True


def set_lock(expected_model: str) -> Dict[str, Any]:
    lock_path = _get_lock_path()
    lock_data = {
        "locked": True,
        "expected_model": expected_model,
        "timestamp": time.time(),
    }
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(lock_data, f, indent=2)
    return lock_data


__all__ = ["status", "get_lock_state", "clear_lock", "set_lock"]
