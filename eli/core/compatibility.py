"""
Compatibility layer for older tests/import paths.

This file must only point at canonical live modules.
"""
from __future__ import annotations

from typing import Any, Dict, List

from eli.execution.executor_enhanced import execute
from eli.execution.router_enhanced import route

try:
    from eli.tools.registry.capabilities import list_capabilities as _list_capabilities
except Exception:
    from eli.tools.registry.capability_registry import list_capabilities as _list_capabilities  # type: ignore


def build_registry():
    return _list_capabilities()


def get_LIST_CAPABILITIES() -> List[Dict[str, Any]]:
    registry = build_registry()
    if isinstance(registry, dict):
        return list(registry.get("tools", []))
    if registry is None:
        return []
    return list(registry)


LIST_CAPABILITIES = get_LIST_CAPABILITIES()


class Router:
    def route(self, text: str) -> Dict[str, Any]:
        return route(text)


try:
    from eli.runtime.eli_agent import EliAgent  # canonical live location
except Exception:
    EliAgent = None  # type: ignore


try:
    from eli.cognition.chat_model import ChatModel
except Exception:
    try:
        from eli.cognition.chat_model import ChatModel  # type: ignore
    except Exception:
        ChatModel = None  # type: ignore


__all__ = [
    "execute",
    "build_registry",
    "get_LIST_CAPABILITIES",
    "LIST_CAPABILITIES",
    "Router",
    "EliAgent",
    "ChatModel",
]
