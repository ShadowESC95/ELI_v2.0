import importlib


def _execute(action, args=None):
    args = args or {}
    ex = importlib.import_module("eli.execution.executor_enhanced")
    return ex.execute(action, args)


def test_executor_system_stats_safe_actions_return_dicts():
    for action in ["SYSTEM_STATS", "CPU_USAGE", "RAM_USAGE"]:
        result = _execute(action, {})
        assert isinstance(result, dict)
        assert "traceback" not in result
        assert result.get("ok") in (True, False)


def test_executor_web_search_empty_query_fails_gracefully():
    result = _execute("WEB_SEARCH", {})
    assert isinstance(result, dict)
    assert "traceback" not in result
    assert result.get("ok") is False
    combined = str(
        result.get("error", "")
        + result.get("content", "")
        + result.get("response", "")
    ).lower()
    assert "query" in combined


def test_executor_notes_and_pomodoro_status_are_safe():
    for action in ["POMODORO_STATUS", "LIST_NOTES", "SEARCH_NOTES"]:
        result = _execute(action, {})
        assert isinstance(result, dict)
        assert "traceback" not in result
        assert result.get("ok") in (True, False)
