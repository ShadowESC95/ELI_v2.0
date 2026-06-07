"""CLAIM: every capability in capability_manifest.json is well-formed and the
in_supported_list flag matches the live executor SUPPORTED_ACTIONS.

One test per manifest capability across several dimensions — examines the
"194 capabilities" claim against the actual manifest + executor.
"""
from __future__ import annotations

import pytest

from . import _helpers as H

_CAPS = H.capabilities()
_IDS = [c.get("action", f"cap{i}") for i, c in enumerate(_CAPS)]
_SUPPORTED = set(H.supported_actions())


def test_manifest_total_matches_capability_count():
    assert H.manifest().get("total") == len(_CAPS)


@pytest.mark.parametrize("cap", _CAPS, ids=_IDS)
def test_capability_active(cap):
    assert cap.get("active") is True, f"{cap.get('action')} is inactive"


@pytest.mark.parametrize("cap", _CAPS, ids=_IDS)
def test_capability_has_action_and_source(cap):
    assert isinstance(cap.get("action"), str) and cap["action"].strip()
    assert isinstance(cap.get("source"), str) and cap["source"].strip()


@pytest.mark.parametrize("cap", _CAPS, ids=_IDS)
def test_capability_flag_types(cap):
    for flag in ("routable", "in_dispatch", "in_supported_list"):
        assert isinstance(cap.get(flag), bool), f"{cap.get('action')}.{flag} not bool"


@pytest.mark.parametrize("cap", _CAPS, ids=_IDS)
def test_supported_flag_matches_executor(cap):
    # The manifest's in_supported_list must agree with the live SUPPORTED_ACTIONS.
    if cap.get("in_supported_list"):
        assert cap["action"] in _SUPPORTED, (
            f"{cap['action']} flagged in_supported_list but not in SUPPORTED_ACTIONS")
