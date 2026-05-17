from __future__ import annotations
from importlib import import_module as _import_module

_mod = _import_module("eli.core.config")
__all__ = getattr(_mod, "__all__", [n for n in dir(_mod) if not n.startswith("_")])
globals().update({n: getattr(_mod, n) for n in __all__})
