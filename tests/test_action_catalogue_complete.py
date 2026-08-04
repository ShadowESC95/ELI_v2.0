"""Every working capability must appear in the catalogue the resolver can reach.

v2 shipped 12 actions with real handlers that were absent from SUPPORTED_ACTIONS —
DOC_GENERATE, PLUGIN_STATUS, LISTEN_FOR_COMMAND and friends. They dispatched fine if
something named them, but llm_intent._catalogue() is built from SUPPORTED_ACTIONS, so
the LLM fallback could never resolve to them. Grammar-constrained decoding turned that
latent gap into a hard one: what is not in the catalogue is not in the grammar, and
therefore unreachable.
"""
from __future__ import annotations

import json
import pathlib

from eli.cognition.llm_intent import _catalogue, _INTERNAL_ACTIONS
from eli.execution.executor_enhanced import SUPPORTED_ACTIONS

_PORTED = (
    "DOC_GENERATE", "SET_AI_MODE", "USER_INFO_REPORT", "SET_USER_NAME",
    "SET_COMMUNICATION_STYLE", "SKIP_YOUTUBE_AD", "ANALYZE_PDF_FOLDER",
    "IMAGE_STATUS", "LISTEN_FOR_COMMAND", "PLUGIN_STATUS", "STT_DIAGNOSTICS",
)


def test_the_ported_actions_are_listed():
    missing = [a for a in _PORTED if a not in set(SUPPORTED_ACTIONS)]
    assert not missing, f"regressed out of SUPPORTED_ACTIONS: {missing}"


def test_the_ported_actions_are_reachable_by_the_resolver():
    """The catalogue is what the grammar is built from — absence means unreachable."""
    cat = set(_catalogue())
    missing = [a for a in _PORTED if a not in cat]
    assert not missing, f"not reachable by llm_intent: {missing}"


def test_every_supported_action_has_a_real_dispatch_branch():
    """Uses the same dispatch detection as the claims suite.

    A first pass here only checked that the action *name appeared* in the executor
    source, which is far too weak: it passed VOICE_DIAGNOSTICS, which is mentioned but
    has no dispatch branch in v2 at all. The claims suite caught it; this now uses the
    same check so the two cannot disagree.
    """
    from tests.claims import _helpers as H
    branches = set(H.executor_action_branches())
    pre_dispatch = {
        "EXPLAIN_LAST_RESPONSE", "NAME_SOURCE_AUDIT", "PERSONAL_MEMORY_DEEP_EXPLAIN",
        "PERSONAL_MEMORY_SUMMARY", "REASONING_MODE_STATUS", "SELF_UPDATE",
    }
    orphans = [a for a in SUPPORTED_ACTIONS
               if a not in branches and a not in pre_dispatch]
    assert not orphans, f"listed but not dispatchable: {orphans}"


def test_no_supported_action_is_missing_from_the_manifest():
    manifest = pathlib.Path("capability_manifest.json")
    if not manifest.is_file():
        return
    known = {c["action"] for c in json.loads(manifest.read_text())["capabilities"]}
    missing = sorted(set(SUPPORTED_ACTIONS) - known)
    assert not missing, f"supported but undeclared: {missing}"


def test_internal_actions_stay_out_of_the_user_catalogue():
    cat = set(_catalogue())
    leaked = sorted(cat & set(_INTERNAL_ACTIONS))
    assert not leaked, f"internal actions leaked into the catalogue: {leaked}"
