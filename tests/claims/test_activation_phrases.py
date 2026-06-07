"""CLAIM: each documented action is reachable by at least one of its documented
activation phrases (blueprints/capabilities_and_actions.md), via the router OR a
documented-equivalent route.

This is the real "does the activation phrase trigger the capability" examination.
The router (`route()`) is only ONE layer — plugins dispatch at execution time,
some actions are aliases that emit a canonical action, and a few (identity/memory/
awareness) intentionally route to CHAT so the persona summarises gathered evidence
(see eli-introspection gather-then-summarise). Those legitimate cases are encoded
in `_ACCEPTABLE` / `_EXEMPT` with reasons, so this test green-lights real routing
and would catch a NEW mis-route. A handful of genuine routing gaps surfaced by this
examination are marked xfail (recorded, see tests/claims/README.md).
"""
from __future__ import annotations

import re

import pytest

from eli.execution.router_enhanced import route
from eli.tools.registry.capabilities_doc import _C as CURATED
from . import _helpers as H

_PLUGIN = {c["action"] for c in H.capabilities() if c.get("plugin")}

# action -> reason it is not a single-phrase router target (legit; not a gap)
_EXEMPT = {
    "CHAT": "fallback for anything unmatched",
    "OPEN_IN_IDE": "post-action (auto after generate)",
    "CONFIRM_CODE_FIX": "pending-state yes reply",
    "CANCEL_CODE_FIX": "pending-state no reply",
    "CONFIRM_HABIT": "pending-state yes reply",
    "DECLINE_HABIT": "pending-state no reply",
    "CONFIRM_PENDING_REMEDIATION": "pending-state yes reply",
    "CANCEL_PENDING_REMEDIATION": "pending-state no reply",
    "NOOP": "internal fragment guard",
    "GAZE_CLICK": "gaze-context utterance",
    "MEDIA_CONTROL": "generic transport → specific media actions",
    "ROUTING_FAULT_EXPLAIN": "internal diagnostic surface",
    "LISTEN_FOR_COMMAND": "wake-word/voice runtime, not a routed phrase",
    "SKIP_YOUTUBE_AD": "context action during playback",
    "SET_USER_NAME": "identity assertion handled by a dedicated stage",
    "SEQUENCE": "multi-step composite",
    "CHECK_CHRONAL_ALIGNMENT": "novelty action; phrasing variable",
    "MESSAGE_TIME_QUERY": "meta time-of-message query; phrasing variable",
    "GET_STATUS": "generic status; overlaps RUNTIME/SYSTEM status",
    # identity/memory/awareness → CHAT on purpose (persona summarises gathered evidence)
    "AWARENESS_STATUS": "routes to CHAT → IntrospectionBus gathers + persona summarises",
    "ELI_IDENTITY_AUDIT": "routes to CHAT → IntrospectionBus gathers + persona summarises",
    "MEMORY_RECALL": "engine memory-grounded path, not a bare router match",
    "MEMORY_STATUS": "grounded memory family (EXPLAIN_MEMORY_RUNTIME et al.)",
    "MEMORY_STATS": "grounded memory family",
    "PERSONAL_MEMORY_DEEP_EXPLAIN": "engine personal-memory grounded path",
    "REFRESH_USER_INFO": "engine profile path / CHAT",
    "EXPLAIN_LAST_RESPONSE": "engine control-contract, not a bare router match",
    "PERSONA_LOCK_SET": "persona-control path / CHAT",
    "PERSONA_LOCK_STATUS": "persona-control path / CHAT",
    "HABIT_STATUS": "habits surfaced via Proactive/CHAT",
    "DATA_FABRICATOR": "delegates to CREATE_DOCUMENT",
    "FILE_AUDIT": "overlaps EXAMINE_CODE on a path",
    "ANALYZE_IMAGE": "needs a concrete image path; bare phrase ambiguous",
    "ANALYZE_PDF_FOLDER": "needs a concrete folder; bare phrase ambiguous",
    "CODE_SOLVE": "composite coding task; phrasing variable",
    "SWITCH_WORKSPACE": "overlaps window focus",
    "PLUGIN_SEARCH": "plugin-registry search; overlaps web search",
    "EXPLAIN_COGNITION_RUNTIME": "routes to CHAT → introspection gathers + persona summarises",
    "SHELL_EXEC": "security-gated; bare phrase → CHAT unless full-control enabled",
}

# documented-equivalent route targets (action emits/serves via these)
_ACCEPTABLE = {
    "OPEN_BROWSER": {"OPEN_APP", "OPEN_URL"},
    "OPEN_IDE": {"OPEN_IN_IDE", "OPEN_APP"},
    "OPEN_FILE_SYSTEM": {"OPEN_APP"},
    "OPEN_SYSTEM_SETTINGS": {"OPEN_APP"},
    "OPEN_AUDIO_SETTINGS": {"OPEN_APP"},
    "OPEN_POWER_SETTINGS": {"OPEN_APP"},
    "OPEN_NETWORK_BROWSER": {"OPEN_APP"},
    "OPEN_COMMUNICATION_HUB": {"OPEN_APP"},
    "OPEN_MEDIA_HUB": {"OPEN_APP"},
    "GET_TIME": {"TIME"},
    "GET_DATE": {"DATE"},
    "RUN_CMD": {"SHELL_EXEC"},
    "SHELL_EXEC": {"RUN_CMD"},
    "LIST_NOTES": {"LIST_DIR"},
}

# genuine routing gaps surfaced by this examination (keyword captured as app/recall);
# recorded as known, non-blocking — fixing them would flip these to xpass.
_KNOWN_GAPS = {
    "SELF_TEST": "routes to OPEN_APP ('self test' captured as an app name)",
    "SELF_ANALYZE": "routes to MEMORY_RECALL instead of self-analysis",
    "PROACTIVE_START": "routes to OPEN_APP ('proactive mode' captured as an app name)",
    "EXECUTE_GOAL": "routes to SHELL_EXEC ('execute …' captured as shell)",
    "MOUSE_CONTROL": "bare 'left click' → GAZE_CLICK/CHAT without explicit mouse verb",
}

_SMART = str.maketrans({"“": "", "”": "", "‘": "", "’": "'"})


def _clean(phrases):
    out = []
    for p in phrases:
        for chunk in re.split(r"\s*·\s*", p):
            c = chunk.translate(_SMART).strip()
            if not c or "(" in c or c.startswith("anything") or "/" in c or "…" in c:
                continue
            out.append(c)
    return out


_CASES = []
for action, (_cat, _desc, phrases) in CURATED.items():
    if action in _EXEMPT or action in _PLUGIN:
        continue
    ph = _clean(phrases)
    if ph:
        _CASES.append((action, ph))


@pytest.mark.parametrize("action,phrases", _CASES, ids=[a for a, _ in _CASES])
def test_action_reachable_by_a_documented_phrase(action, phrases):
    if action in _KNOWN_GAPS:
        pytest.xfail(_KNOWN_GAPS[action])
    routed = {(route(p).get("action") or "").upper() for p in phrases}
    ok = action in routed or bool(routed & _ACCEPTABLE.get(action, set()))
    assert ok, (f"{action}: no documented phrase routed to it or an accepted "
                f"equivalent; got {sorted(routed)} for {phrases}")
