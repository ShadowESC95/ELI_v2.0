# eli/plugins/router_plugin_intents.py
"""
Plugin-related intent patterns for router_enhanced.py.

Import and call route_plugin_intent() early in the route() function,
before the generic CHAT fallback.

Example insertion in router_enhanced.py route():
    from eli.execution.router_plugin_intents import route_plugin_intent
    ...
    plug = route_plugin_intent(raw, low)
    if plug:
        return plug
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional


def route_plugin_intent(raw: str, low: str) -> Optional[Dict[str, Any]]:
    """
    Returns a route dict if the input matches a plugin management intent,
    otherwise returns None.
    """

    # LIST INSTALLED
    if re.search(r"\b(list|show|what)\b.{0,20}\bplugins?\b", low) and "available" not in low:
        return {"action": "LIST_PLUGINS", "args": {}, "confidence": 0.92}

    # LIST AVAILABLE / BROWSE
    if re.search(r"\b(list|show|browse|available|what).{0,20}\b(available\s+)?plugins?\b", low):
        return {"action": "LIST_AVAILABLE_PLUGINS", "args": {}, "confidence": 0.92}

    # INSTALL
    m = re.search(
        r"\b(install|add|download|get)\b.{0,30}\bplugin\b(?:\s+(?:for|called|named)?\s*[\"']?([a-z0-9_\-]+)[\"']?)?",
        low,
    )
    if not m:
        m = re.search(
            r"\b(install|add)\b\s+(?:the\s+)?[\"']?([a-z0-9_\-]+)[\"']?\s+plugin\b",
            low,
        )
    if m:
        groups = m.groups()
        plugin_id = (groups[-1] or "").strip() if groups else ""
        return {
            "action": "INSTALL_PLUGIN",
            "args": {"plugin_id": plugin_id},
            "confidence": 0.93 if plugin_id else 0.75,
        }

    # UNINSTALL / REMOVE
    m = re.search(
        r"\b(uninstall|remove|delete)\b.{0,30}\bplugin\b",
        low,
    )
    if not m:
        m = re.search(
            r"\b(uninstall|remove)\b\s+(?:the\s+)?[\"']?([a-z0-9_\-]+)[\"']?\s+plugin\b",
            low,
        )
    if m:
        m2 = re.search(r"\b(uninstall|remove|delete)\b\s+(?:the\s+)?([a-z0-9_\-]+)\s+plugin\b", low)
        plugin_id = m2.group(2) if m2 else ""
        return {
            "action": "UNINSTALL_PLUGIN",
            "args": {"plugin_id": plugin_id},
            "confidence": 0.93 if plugin_id else 0.75,
        }

    # ENABLE
    m = re.search(r"\benable\b\s+(?:the\s+)?([a-z0-9_\-]+)\s+plugin\b", low)
    if m:
        return {"action": "ENABLE_PLUGIN", "args": {"plugin_id": m.group(1)}, "confidence": 0.93}

    # DISABLE
    m = re.search(r"\bdisable\b\s+(?:the\s+)?([a-z0-9_\-]+)\s+plugin\b", low)
    if m:
        return {"action": "DISABLE_PLUGIN", "args": {"plugin_id": m.group(1)}, "confidence": 0.93}

    # REFRESH REGISTRY
    if re.search(r"\brefresh\b.{0,20}\b(plugin\s+)?(registry|plugins)\b", low):
        return {"action": "REFRESH_PLUGIN_REGISTRY", "args": {}, "confidence": 0.90}

    return None
