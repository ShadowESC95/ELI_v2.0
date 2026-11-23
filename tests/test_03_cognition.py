"""
test_03_cognition.py
====================
Tests for eli.cognition — orchestrator, agent bus, persona, inference.
"""
import pytest
import importlib


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


def test_the_inference_broker_passes_top_p_to_the_model():
    """_call took top_p and never handed it on, so every caller's nucleus setting was ignored."""
    from eli.cognition.inference_broker import InferenceBroker
    seen = {}

    class GI:
        @staticmethod
        def generate(prompt, **kw):
            seen.update(kw)
            yield "ok"

    b = InferenceBroker.__new__(InferenceBroker)
    b._gguf = GI
    assert b._call("hi", "sys", 8, 0.2, 0.55) == "ok" and seen["top_p"] == 0.55
