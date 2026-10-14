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
    # Use a complete sentence with a terminator so the fragment guard does not
    # intercept it and route to NOOP before the GGUF layer is reached.
    result = engine_with_mocks.process("Hello, how are you today?", stream=False)
    assert result.get("content") == "Mocked chat response" or result.get("response")

def test_engine_verify_persona_lock():
    # verify_persona_lock() returns False when no GGUF model is loaded — correct
    # behaviour. The lock is only "verified" when a model is actually running.
    engine = CognitiveEngine(auto_init_gguf=False)
    assert engine.verify_persona_lock() is False


def test_the_loaded_model_is_the_lock_and_another_file_in_the_settings_is_not_a_break(monkeypatch):
    """Live (2.5.11): the settings named a 7B, the 35B picked at start-up was loaded, and the check
    called that a broken lock: the 35B was loaded again (20 GB) before the first reply."""
    import types
    from eli.kernel import engine as eng
    loaded = "/models/Qwen3.6-35B-A3B-Q4_K_M.gguf"
    fake = types.SimpleNamespace(is_loaded=lambda: True, _loaded_model_path_str=lambda: loaded,
                                 get_model_path=lambda: "/models/Qwen2.5-7B-Instruct-Q4_K_M.gguf")
    monkeypatch.setattr(eng, "gguf_inference", fake)
    me = eng.CognitiveEngine.__new__(eng.CognitiveEngine)
    me._gguf_available, me._model_path = True, "/models/an-earlier-model.gguf"
    assert me.verify_persona_lock() is True and me._model_path == loaded
    fake.is_loaded = lambda: False
    assert me.verify_persona_lock() is False, "nothing in memory is still a lock to repair"
