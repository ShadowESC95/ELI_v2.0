"""CLAIM: every executor SUPPORTED_ACTION has a dispatch branch: nothing is advertised that routes
but cannot run."""
from __future__ import annotations

from . import _helpers as H


def test_every_supported_action_is_handled():
    unhandled = set(H.supported_actions()) - H.executor_action_branches()
    assert not unhandled, f"SUPPORTED_ACTIONS with no executor dispatch path: {sorted(unhandled)}"
