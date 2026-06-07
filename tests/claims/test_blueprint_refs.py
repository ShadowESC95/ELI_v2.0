"""CLAIM: every code path/module the blueprints reference actually exists.

Parses path-like `*.py` and dotted `eli.x.y` references out of all blueprint docs
and asserts each resolves — so the documentation can't claim a file/module that
isn't there.
"""
from __future__ import annotations

import importlib.util

import pytest

from . import _helpers as H

_FILE_REFS = H.blueprint_file_refs()
_MOD_REFS = H.blueprint_module_refs()


@pytest.mark.parametrize("ref", _FILE_REFS, ids=list(_FILE_REFS))
def test_blueprint_file_reference_exists(ref):
    assert (H.REPO / ref).exists(), f"blueprints reference a non-existent file: {ref}"


def _resolves(dotted: str) -> bool:
    try:
        if importlib.util.find_spec(dotted) is not None:
            return True
    except (ImportError, AttributeError, ValueError):
        pass
    return False


@pytest.mark.parametrize("ref", _MOD_REFS, ids=list(_MOD_REFS))
def test_blueprint_module_reference_importable(ref):
    # Either the ref is a module, or it's `module.symbol` whose module resolves.
    ok = _resolves(ref) or ("." in ref and _resolves(ref.rsplit(".", 1)[0]))
    assert ok, f"blueprints reference an unresolvable module/symbol: {ref}"
