import pytest
from unittest.mock import patch, MagicMock

def test_e2e_chat_flow(engine_with_mocks):
    engine = engine_with_mocks
    result = engine.process("Who are you?", stream=False)
    # The result may be a dict or a string; handle both
    if isinstance(result, dict):
        assert result.get("content") or result.get("response")
    else:
        assert isinstance(result, str) and len(result) > 0
