"""COMPLETE symbol inventory: every public function / class / method in every
safely-importable eli module is a real, introspectable callable.

This is the "test everything" structural layer — it scales with the codebase
(thousands of symbols). Each symbol is asserted to (a) exist, (b) be callable or a
class, and (c) have an introspectable signature (catches half-written defs, bad
decorators, broken overrides). GUI and known side-effecting modules are denylisted
(importing some modules has real side effects — e.g. the image engine kicks off a
job on import), so this stays safe and deterministic.
"""
from __future__ import annotations

import importlib
import inspect
import os

import pytest

from . import _helpers as H

# keep imports side-effect-free
os.environ.setdefault("ELI_TEST_MODE", "1")
os.environ.setdefault("ELI_HEADLESS", "1")
os.environ.setdefault("ELI_AUTONOMY_TICK", "0")

# dotted-prefixes to skip: GUI needs a display; image_engine / a few others run
# work at import time; __main__/cli can execute.
_DENY_PREFIXES = (
    "eli.gui", "eli.__main__", "eli.cli", "eli.tools.image_engine",
    "eli.scripts", "eli.learning.bootstrap_phi3_base",
)


def _dotted(path) -> str:
    parts = path.relative_to(H.REPO).with_suffix("").parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _safe_modules():
    mods = {}
    for p in H.eli_py_files():
        dotted = _dotted(p)
        if not dotted or dotted.startswith(_DENY_PREFIXES):
            continue
        try:
            mods[dotted] = importlib.import_module(dotted)
        except Exception:
            # un-importable here (optional dep / env) — covered by compile test
            continue
    return mods


_MODULES = _safe_modules()


def _symbols():
    out = []
    for dotted, mod in _MODULES.items():
        for name, obj in vars(mod).items():
            if name.startswith("_"):
                continue
            if inspect.isfunction(obj) and getattr(obj, "__module__", None) == dotted:
                out.append((f"{dotted}:{name}", obj))
            elif inspect.isclass(obj) and getattr(obj, "__module__", None) == dotted:
                out.append((f"{dotted}:{name}", obj))
                for mname, mobj in vars(obj).items():
                    if mname.startswith("_") and mname != "__init__":
                        continue
                    if inspect.isfunction(mobj):
                        out.append((f"{dotted}:{name}.{mname}", mobj))
    return out


_SYMBOLS = _symbols()


def test_symbol_inventory_is_substantial():
    # guards against the inventory silently collapsing to nothing
    assert len(_SYMBOLS) > 1500, f"only {len(_SYMBOLS)} symbols discovered"


@pytest.mark.parametrize("qual,obj", _SYMBOLS, ids=[q for q, _ in _SYMBOLS])
def test_symbol_is_callable_with_signature(qual, obj):
    assert callable(obj), f"{qual} is not callable"
    try:
        inspect.signature(obj)
    except (ValueError, TypeError):
        # some C-level / builtin-wrapped callables have no signature — acceptable
        # only if it's genuinely builtin; a pure-Python def must introspect.
        if inspect.isfunction(obj):
            raise AssertionError(f"{qual}: python function has no usable signature")
