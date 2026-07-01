"""Control contracts — action normalisation, control classification, control-text
routing, and the anti-confabulation evidence check.

These govern which turns are treated as grounded "control" surfaces (status/identity
reported from real evidence) versus free chat, and the guard that rejects an output
which contradicts or dodges its evidence. Pure, model-free logic. Runs in the normal
suite.
"""
from __future__ import annotations

import pytest

from eli.runtime import control_contracts as cc


# --------------------------------------------------------------------------- #
# normalise_action
# --------------------------------------------------------------------------- #
def test_normalise_action():
    assert cc.normalise_action("runtime_status") == "RUNTIME_STATUS"
    assert cc.normalise_action("  chat ") == "CHAT"
    assert cc.normalise_action(None) == "CHAT"
    assert cc.normalise_action("") == "CHAT"


# --------------------------------------------------------------------------- #
# is_control_action
# --------------------------------------------------------------------------- #
def test_is_control_action_true_for_status():
    assert cc.is_control_action("RUNTIME_STATUS") is True
    assert cc.is_control_action("runtime_status") is True  # normalised first


def test_is_control_action_false_for_chat_and_side_effects():
    assert cc.is_control_action("CHAT") is False
    assert cc.is_control_action("OPEN_APP") is False
    assert cc.is_control_action(None) is False


# --------------------------------------------------------------------------- #
# route_control_text
# --------------------------------------------------------------------------- #
def test_route_self_update():
    assert cc.route_control_text("update yourself") == "SELF_UPDATE"
    assert cc.route_control_text("self-update") == "SELF_UPDATE"


def test_route_last_response_trace():
    assert cc.route_control_text("what is your confidence in your last response") == "EXPLAIN_LAST_RESPONSE"


def test_route_plain_chat_is_not_control():
    assert cc.route_control_text("tell me a joke about cats") is None


# --------------------------------------------------------------------------- #
# output_violates_evidence — the anti-confabulation guard
# --------------------------------------------------------------------------- #
def test_empty_output_violates():
    assert cc.output_violates_evidence("", "some evidence") is True
    assert cc.output_violates_evidence("   ", "some evidence") is True


def test_question_echo_violates():
    # Echoing a question back instead of answering from evidence is a violation.
    assert cc.output_violates_evidence("How do you feel today?", "") is True


def test_grounded_statement_does_not_violate():
    # A plain declarative answer consistent with the evidence passes the guard.
    ok = cc.output_violates_evidence(
        "The GPU is running at 45 degrees.", "gpu temperature 45 degrees"
    )
    assert ok is False
