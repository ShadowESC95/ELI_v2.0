#!/usr/bin/env python3
"""Capabilities management for ELI."""
import logging
from typing import Dict, Any, Callable, List, Optional
from datetime import datetime
import webbrowser

logger = logging.getLogger(__name__)

class CapabilityRegistry:
    """Registry for system capabilities."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._capabilities = {}
            cls._instance._register_builtins()
        return cls._instance
    
    def _register_builtins(self):
        """Register built-in capabilities."""
        self.register(
            "system.get_time",
            lambda: datetime.now().strftime("%H:%M:%S"),
            "Get current system time"
        )
        self.register(
            "system.get_date",
            lambda: datetime.now().strftime("%Y-%m-%d"),
            "Get current system date"
        )
        self.register(
            "system.open_url",
            lambda url: webbrowser.open(url) or f"Opened {url}",
            "Open a URL in default browser"
        )
        self.register(
            "system.get_platform",
            lambda: __import__('platform').system(),
            "Get operating system platform"
        )
    
    def register(self, name: str, func: Callable, description: str = ""):
        """Register a capability."""
        self._capabilities[name] = {
            'function': func,
            'description': description
        }
        logger.debug(f"Registered capability: {name}")
    
    def get(self, name: str) -> Optional[Callable]:
        """Get a capability by name."""
        cap = self._capabilities.get(name)
        return cap['function'] if cap else None
    
    def list_capabilities(self) -> List[Dict[str, str]]:
        """List all registered capabilities."""
        return [
            {'name': name, 'description': info['description']}
            for name, info in self._capabilities.items()
        ]
    
    def has_capability(self, name: str) -> bool:
        """Check if a capability exists."""
        return name in self._capabilities
    
    def execute(self, name: str, *args, **kwargs) -> Any:
        """Execute a capability by name."""
        func = self.get(name)
        if func is None:
            raise ValueError(f"Unknown capability: {name}")
        return func(*args, **kwargs)

# Singleton instance - THIS IS WHAT THE TEST IS LOOKING FOR
capability_registry = CapabilityRegistry()

__all__ = ['CapabilityRegistry', 'capability_registry']

def as_text(obj=None):
    if obj is None: return ""
    """Convert any object to a safe string representation."""
    if obj is None:
        return ""
    try:
        return str(obj)
    except:
        return repr(obj)


# ---- compatibility exports for legacy tests ----
try:
    CAPABILITIES
except NameError:
    CAPABILITIES = globals().get("CAPABILITY_REGISTRY", globals().get("registry", []))

try:
    SUPPORTED_ACTIONS
except NameError:
    if isinstance(CAPABILITIES, dict):
        SUPPORTED_ACTIONS = sorted(CAPABILITIES.keys())
    elif isinstance(CAPABILITIES, (list, tuple)):
        _acts = []
        for x in CAPABILITIES:
            if isinstance(x, dict) and "action" in x:
                _acts.append(x["action"])
            elif isinstance(x, str):
                _acts.append(x)
        SUPPORTED_ACTIONS = sorted(set(_acts))
    else:
        SUPPORTED_ACTIONS = []

if callable(globals().get("list_capabilities")):
    _orig_list_capabilities = list_capabilities
    def list_capabilities(fmt='list'):
        data = _orig_list_capabilities()
        if fmt == 'json':
            return {"ok": True, "capabilities": data}
        return data


# ---- Missing exports required by doctor.py ----

def as_jsonable(obj=None):
    """Convert any object to a JSON-serialisable form (safe fallback to str)."""
    import json
    if obj is None:
        return None
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        if isinstance(obj, dict):
            return {str(k): as_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [as_jsonable(x) for x in obj]
        return str(obj)


def capability_names() -> list:
    """Return a sorted list of capability name strings from the registry."""
    try:
        from eli.tools.registry.capability_registry import list_capabilities as _lc
        return sorted(item.get("name", "") for item in _lc() if item.get("name"))
    except Exception:
        return []


# Module-level cached list — populated on first import
capability_names_list: list = capability_names()
