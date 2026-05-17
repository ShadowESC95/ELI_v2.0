from __future__ import annotations

from threading import RLock
from typing import Any, Dict, List, Optional

_LOCK = RLock()
_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register_capability(name: str | Dict[str, Any], payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if isinstance(name, dict):
        item = dict(name)
        cap_name = str(item.get("name") or item.get("id") or "").strip()
    else:
        cap_name = str(name).strip()
        item = dict(payload or {})
        item.setdefault("name", cap_name)
    if not cap_name:
        raise ValueError("capability name required")
    with _LOCK:
        _REGISTRY[cap_name] = item
        return dict(_REGISTRY[cap_name])


def get_capability(name: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        item = _REGISTRY.get(str(name).strip())
        return dict(item) if item is not None else None


def list_capabilities() -> List[Dict[str, Any]]:
    with _LOCK:
        return [dict(v) for _, v in sorted(_REGISTRY.items())]


register = register_capability
get = get_capability
list = list_capabilities
