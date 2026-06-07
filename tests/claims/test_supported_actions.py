"""CLAIM: every executor SUPPORTED_ACTION is declared in the manifest AND is
actually handled (a dispatch branch, or a known pre-dispatch handler).

Examines the "155 routable actions" claim — no orphan actions that route but
can't execute.
"""
from __future__ import annotations

import pytest

from . import _helpers as H

_SUPPORTED = list(H.supported_actions())
_MANIFEST_ACTIONS = {c["action"] for c in H.capabilities()}
_BRANCHES = H.executor_action_branches()

# Actions dispatched NOT via a simple `if a == "X"` branch but via
# _action_pre_dispatch / control_contracts / router-owned grounded surfaces.
_PRE_DISPATCH_HANDLED = {
    "EXPLAIN_LAST_RESPONSE", "NAME_SOURCE_AUDIT", "PERSONAL_MEMORY_DEEP_EXPLAIN",
    "PERSONAL_MEMORY_SUMMARY", "REASONING_MODE_STATUS", "SELF_UPDATE",
}


@pytest.mark.parametrize("action", _SUPPORTED, ids=_SUPPORTED)
def test_supported_action_in_manifest(action):
    assert action in _MANIFEST_ACTIONS, f"{action} supported but missing from manifest"


@pytest.mark.parametrize("action", _SUPPORTED, ids=_SUPPORTED)
def test_supported_action_is_handled(action):
    assert action in _BRANCHES or action in _PRE_DISPATCH_HANDLED, (
        f"{action} is a SUPPORTED_ACTION but has no executor dispatch path")
