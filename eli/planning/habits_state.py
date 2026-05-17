"""State management helpers for this ELI subsystem."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict

_STATE_PATH = Path(os.environ.get("ELI_STATE_FILE", str(Path.home() / ".eli_state.json")))

def _load_state() -> Dict[str, Any]:
    try:
        if _STATE_PATH.exists():
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except:
        pass
    return {}

def _save_state(state: Dict[str, Any]) -> None:
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except:
        pass

# Export the functions your GUI expects (adjust these names based on your actual usage)
# From your GUI: "from brain import state as eli_state" – likely eli_state has load/save etc.
def load_state() -> Dict[str, Any]:
    return _load_state()

def save_state(state: Dict[str, Any]) -> None:
    _save_state(state)

def get_user_name() -> str:
    try:
        from eli.kernel.state import get_user_name as _get_user_name
        return (_get_user_name("") or "").strip()
    except Exception:
        state = _load_state()
        return state.get("user_name", "")

def set_user_name(name: str) -> None:
    n = (name or "").strip()
    if not n:
        return
    try:
        from eli.kernel.state import set_user_name as _set_user_name
        _set_user_name(n)
    except Exception:
        state = _load_state()
        state["user_name"] = n
        _save_state(state)
