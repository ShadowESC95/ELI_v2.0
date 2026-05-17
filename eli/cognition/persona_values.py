from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "memory_policy": "balanced",
    "verbosity": "normal",
    "safety_mode": "strict",
}

def _values_path() -> Path:
    try:
        from eli.core.paths import get_paths
        default = get_paths().config_dir / "values.json"
    except Exception:
        default = Path(os.environ.get("ELI_VALUES_FILE", str(get_paths().config_dir / "values.json")))
    return Path(os.environ.get("ELI_VALUES_FILE", str(default))).expanduser().resolve()

def load_values() -> Dict[str, Any]:
    p = _values_path()
    if not p.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            merged = dict(DEFAULTS)
            merged.update(data)
            return merged
    except Exception:
        pass
    return dict(DEFAULTS)

def save_values(values: Dict[str, Any]) -> Dict[str, Any]:
    p = _values_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(DEFAULTS)
    merged.update(values)
    p.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return merged

def set_value(key: str, value: Any) -> Dict[str, Any]:
    values = load_values()
    values[str(key)] = value
    return save_values(values)

__all__ = ["DEFAULTS", "load_values", "save_values", "set_value"]
