"""
test_03_cognition.py
====================
Tests for eli.cognition — orchestrator, agent bus, persona, inference.
"""
import pytest
import importlib


def test_cognition_package_init():
    mod = importlib.import_module("eli.cognition")
    assert mod is not None


def test_cognition_orchestrator_has_class():
    mod = importlib.import_module("eli.cognition.orchestrator")
    syms = dir(mod)
    matches = [s for s in syms if "Orchestrat" in s]
    assert matches, f"No Orchestrator-like class in orchestrator.py: {syms}"


def test_cognition_agent_bus_has_class():
    mod = importlib.import_module("eli.cognition.agent_bus")
    syms = dir(mod)
    matches = [s for s in syms if "Bus" in s or "Agent" in s]
    assert matches, f"No AgentBus-like class: {syms}"


def test_cognition_persona_has_class():
    mod = importlib.import_module("eli.cognition.persona")
    syms = dir(mod)
    matches = [s for s in syms if "Persona" in s]
    assert matches, f"No Persona class in persona.py: {syms}"


def test_cognition_gguf_inference_loadable():
    mod = importlib.import_module("eli.cognition.gguf_inference")
    assert mod is not None


def test_cognition_context_builder_loadable():
    mod = importlib.import_module("eli.cognition.context_builder")
    assert mod is not None


def test_cognition_context_synthesiser_loadable():
    mod = importlib.import_module("eli.cognition.context_synthesiser")
    assert mod is not None


def test_cognition_engagement_tracker_loadable():
    mod = importlib.import_module("eli.cognition.engagement_tracker")
    assert mod is not None


def test_cognition_hyde_loadable():
    mod = importlib.import_module("eli.cognition.hyde")
    assert mod is not None


def test_cognition_inference_broker_loadable():
    mod = importlib.import_module("eli.cognition.inference_broker")
    assert mod is not None


def test_cognition_introspection_agent_loadable():
    mod = importlib.import_module("eli.cognition.introspection_agent")
    assert mod is not None


def test_cognition_llm_intent_loadable():
    mod = importlib.import_module("eli.cognition.llm_intent")
    assert mod is not None


def test_cognition_output_governor_loadable():
    mod = importlib.import_module("eli.cognition.output_governor")
    assert mod is not None


def test_cognition_persona_hygiene_loadable():
    mod = importlib.import_module("eli.cognition.persona_hygiene")
    assert mod is not None


def test_cognition_persona_status_loadable():
    mod = importlib.import_module("eli.cognition.persona_status")
    assert mod is not None


def test_cognition_persona_updater_loadable():
    mod = importlib.import_module("eli.cognition.persona_updater")
    assert mod is not None


def test_cognition_persona_values_loadable():
    mod = importlib.import_module("eli.cognition.persona_values")
    assert mod is not None


def test_cognition_reranker_loadable():
    mod = importlib.import_module("eli.cognition.reranker")
    assert mod is not None


def test_cognition_response_governance_loadable():
    mod = importlib.import_module("eli.cognition.response_governance")
    assert mod is not None


def test_cognition_response_sanitizer_loadable():
    mod = importlib.import_module("eli.cognition.response_sanitizer")
    assert mod is not None


def test_cognition_user_info_builder_loadable():
    mod = importlib.import_module("eli.cognition.user_info_builder")
    assert mod is not None


def test_cognition_working_memory_loadable():
    mod = importlib.import_module("eli.cognition.working_memory")
    assert mod is not None


def test_cognition_chat_model_loadable():
    mod = importlib.import_module("eli.cognition.chat_model")
    assert mod is not None
