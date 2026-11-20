import pytest
from unittest.mock import patch, MagicMock
from eli.execution.executor_enhanced import execute

def test_executor_open_app(monkeypatch):
    launched = []
    monkeypatch.setattr("eli.execution.effectors.system_helpers.open_app_with_timeout",
                        lambda argv, timeout=30: launched.append(argv) or {"ok": True, "spawned": True, "argv": argv})
    monkeypatch.setattr("eli.system.portable_app_control._popen", lambda args: launched.append(args) or True)
    result = execute("OPEN_APP", {"name": "firefox"})
    assert result["ok"] is True and launched and "firefox" in " ".join(launched[0])

@patch("subprocess.run")
def test_executor_shell_exec(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout="")
    result = execute("SHELL_EXEC", {"cmd": "echo hi"})
    assert result["ok"] is True

def test_executor_time():
    result = execute("TIME", {})
    assert ":" in result["content"]

def test_executor_date():
    result = execute("DATE", {})
    assert any(x in result["content"] for x in ("202","20"))

@pytest.mark.parametrize("action", ["MEMORY_STORE", "MEMORY_RECALL"])
def test_executor_memory_actions(action, memory_instance):
    with patch("eli.execution.executor_enhanced._get_canonical_memory", return_value=memory_instance):
        if action == "MEMORY_STORE":
            result = execute(action, {"text": "test store"})
            assert result["ok"] is True
        else:
            # Pre-store a memory
            memory_instance.store_memory("test content")
            result = execute(action, {"query": "test"})
            assert result["ok"] is True
            # Some recall results may be empty if faiss missing; just check ok


def test_a_whole_prompt_sent_to_the_model_is_not_answered_by_a_keyword_shortcut(monkeypatch):
    """The engine sends its assembled prompt here with skip_router. Its rules mention "persistent
    memory", so a recalled code was answered with a JSON dump of the memory database."""
    import eli.execution.executor_enhanced as ex
    import eli.cognition.gguf_inference as gi
    monkeypatch.setattr(gi, "load_model", lambda *a, **k: object())
    monkeypatch.setattr(gi, "chat_completion", lambda msg, system=None, **k: "KEY-A01")
    monkeypatch.setattr(ex, "_convlog_append", lambda *a, **k: None)
    prompt = ("You DO have a persistent memory. Speak as yourself.\n\nAGENT DATA:\nKEY-A01\n\n"
              "USER QUESTION:\nRecall the exact code for my Fern project.\n\nYOUR ANSWER:")
    out = ex.chat(prompt, skip_router=True)
    assert out["response"] == "KEY-A01" and "memory_audit" not in out
