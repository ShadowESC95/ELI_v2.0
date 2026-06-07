"""Shared loaders for the claims-verification suite.

The claims suite examines the PROJECT vs its CLAIMS — the capability manifest, the
executor's action surface, the blueprint documents, and the module tree — and
asserts they actually line up. Everything is derived from real artifacts so the
test count scales with the project and the assertions are grounded, not invented.
"""
from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads((REPO / "capability_manifest.json").read_text(encoding="utf-8"))


def capabilities() -> list:
    return list(manifest().get("capabilities", []))


@lru_cache(maxsize=1)
def supported_actions() -> tuple:
    from eli.execution.executor_enhanced import SUPPORTED_ACTIONS
    return tuple(sorted(SUPPORTED_ACTIONS))


@lru_cache(maxsize=1)
def executor_action_branches() -> frozenset:
    from eli.tools.registry.capability_updater import extract_executor_actions
    return frozenset(extract_executor_actions(REPO / "eli" / "execution" / "executor_enhanced.py"))


@lru_cache(maxsize=1)
def eli_py_files() -> tuple:
    return tuple(sorted(
        p for p in (REPO / "eli").rglob("*.py")
        if "__pycache__" not in p.parts
    ))


def rel(p: Path) -> str:
    return str(p.relative_to(REPO))


@lru_cache(maxsize=1)
def blueprint_files() -> tuple:
    return tuple(sorted((REPO / "blueprints").glob("*.md")))


_FILE_RE = re.compile(r"`([a-zA-Z0-9_][a-zA-Z0-9_./\-]*\.py)`")
_MOD_RE = re.compile(r"`(eli\.[a-z0-9_]+(?:\.[a-z0-9_]+)+)`")
_TOP_DIRS = ("eli/", "tools/", "tests/", "blueprints/", "scripts/", "config/")


@lru_cache(maxsize=1)
def blueprint_file_refs() -> tuple:
    """Path-like `*.py` references in the blueprints (must contain a '/' and start
    under a known top dir — bare filenames are too ambiguous to verify)."""
    refs = set()
    for f in blueprint_files():
        for m in _FILE_RE.findall(f.read_text(encoding="utf-8", errors="ignore")):
            if "/" in m and m.startswith(_TOP_DIRS):
                refs.add(m)
    return tuple(sorted(refs))


@lru_cache(maxsize=1)
def blueprint_module_refs() -> tuple:
    """Dotted `eli.x.y` module references in the blueprints."""
    refs = set()
    for f in blueprint_files():
        for m in _MOD_RE.findall(f.read_text(encoding="utf-8", errors="ignore")):
            refs.add(m)
    return tuple(sorted(refs))
