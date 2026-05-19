import pytest
from eli.kernel.engine import CognitiveEngine
from unittest.mock import patch, MagicMock

def test_engine_init():
    engine = CognitiveEngine(auto_init_gguf=False)
    assert engine is not None
    assert engine.memory is not None
    assert engine.session_id is not None

def test_engine_parse_intent():
    engine = CognitiveEngine(auto_init_gguf=False)
    intent = engine.parse_intent("what time is it", [])
    assert intent["action"] in ("TIME", "CHAT")

@patch("eli.execution.executor_enhanced.execute")
def test_engine_process_non_chat(mock_execute):
    mock_execute.return_value = {"ok": True, "content": "mocked", "response": "mocked"}
    engine = CognitiveEngine(auto_init_gguf=False)
    result = engine.process("screenshot", stream=False)
    assert result.get("action") == "SCREENSHOT" or result.get("content")

@patch("eli.cognition.gguf_inference.chat_completion", return_value="Mocked chat response")
def test_engine_process_chat(mock_gguf, engine_with_mocks):
    result = engine_with_mocks.process("hello", stream=False)
    assert result.get("content") == "Mocked chat response" or result.get("response")

def test_engine_verify_persona_lock():
    engine = CognitiveEngine(auto_init_gguf=False)
    assert engine.verify_persona_lock() is True
