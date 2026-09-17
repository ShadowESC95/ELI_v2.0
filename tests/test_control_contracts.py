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


# --------------------------------------------------------------------------- #
# output_violates_evidence — concrete runtime-parameter terms
#
# These seven terms (context size, gpu layers, batch size, cpu threads, model
# path, user database, agent database) used to be blanket-exempted from the
# evidence check, so the model could state any value for them with zero
# evidence backing. The exemption existed because evidence renders these
# under a machine-style key (n_gpu_layers, batch_size/n_batch, model_path,
# user_db, agent_db) while prose says the human phrase — a naive substring
# check of the phrase against machine-keyed evidence would false-positive.
# _CONCRETE_TERM_ALIASES closes the confabulation hole while still accepting
# evidence phrased under its real key.
# --------------------------------------------------------------------------- #
def test_gpu_layers_claim_with_no_evidence_violates():
    # No mention of GPU layers anywhere in the evidence — this used to be
    # silently allowed through by the blanket exemption.
    assert cc.output_violates_evidence(
        "I'm using 32 gpu layers on this run.", "provider: custom_gguf"
    ) is True


def test_gpu_layers_claim_grounded_by_machine_key_does_not_violate():
    # Evidence phrases the same fact under its real key (n_gpu_layers), not
    # the human phrase "gpu layers" — must still be accepted.
    assert cc.output_violates_evidence(
        "I'm using 32 gpu layers on this run.", '{"n_gpu_layers": 32}'
    ) is False


def test_batch_size_claim_with_no_evidence_violates():
    assert cc.output_violates_evidence(
        "The batch size is 512.", "provider: custom_gguf"
    ) is True


def test_batch_size_claim_grounded_by_machine_key_does_not_violate():
    assert cc.output_violates_evidence(
        "The batch size is 512.", '{"batch_size": 512}'
    ) is False


def test_user_database_claim_with_no_evidence_violates():
    assert cc.output_violates_evidence(
        "I checked your user database for that.", "provider: custom_gguf"
    ) is True


def test_user_database_claim_grounded_by_machine_key_does_not_violate():
    assert cc.output_violates_evidence(
        "I checked your user database for that.", "- user_db: /data/db/user.sqlite3"
    ) is False
