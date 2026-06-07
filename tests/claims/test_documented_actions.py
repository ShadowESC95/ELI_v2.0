"""CLAIM: every action documented in blueprints/capabilities_and_actions.md (the
curated reference) is a real, routable/plugin-backed manifest capability.

Examines the public capability reference against the live manifest.
"""
from __future__ import annotations

import pytest

from . import _helpers as H

from eli.tools.registry.capabilities_doc import _C as CURATED  # action -> (cat, desc, [phrases])

_ACTIONS = sorted(CURATED.keys())
_CAP_BY_ACTION = {c["action"]: c for c in H.capabilities()}


@pytest.mark.parametrize("action", _ACTIONS, ids=_ACTIONS)
def test_documented_action_in_manifest(action):
    assert action in _CAP_BY_ACTION, f"{action} is documented but not in the manifest"


@pytest.mark.parametrize("action", _ACTIONS, ids=_ACTIONS)
def test_documented_action_is_reachable(action):
    cap = _CAP_BY_ACTION[action]
    assert cap.get("routable") or cap.get("in_supported_list") or cap.get("plugin"), (
        f"{action} is documented but neither routable, supported, nor plugin-backed")
