import pytest
from eli.cognition.agent_bus import AgentBus, get_bus

def test_agent_bus_dispatch_chat():
    bus = AgentBus(max_workers=2)
    result = bus.dispatch("hello", {"action": "CHAT"}, session_id="test", user_id="test")
    assert result.intent_action == "CHAT"
    # Some agents may have contributed
    assert isinstance(result.agents_used, list)
    # confidence between 0 and 1
    assert 0 <= result.aggregated_confidence <= 1

def test_agent_bus_dispatch_runtime_status():
    bus = AgentBus(max_workers=2)
    result = bus.dispatch("what is your runtime status?", {"action": "RUNTIME_STATUS"}, session_id="test", user_id="test")
    # Expect system agent to contribute
    assert "system" in result.agents_used or "capability" in result.agents_used

def test_agent_bus_dispatch_memory_recall():
    bus = AgentBus(max_workers=2)
    result = bus.dispatch("what do you know about me?", {"action": "MEMORY_RECALL"}, session_id="test", user_id="test")
    assert result.intent_action == "MEMORY_RECALL"
