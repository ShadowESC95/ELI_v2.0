from eli.execution.router_enhanced import route


def _action(text):
    r = route(text)
    return r.get("action"), r


def test_web_search_plugin_route():
    action, result = _action("web search entropy field simulations")
    assert action == "WEB_SEARCH"
    assert result["args"]["query"] == "entropy field simulations"


def test_tts_plugin_route():
    action, result = _action("say system check complete")
    assert action == "SPEAK"
    assert result["args"]["text"] == "system check complete"


def test_system_stats_plugin_routes():
    assert _action("system stats")[0] == "SYSTEM_STATS"
    assert _action("cpu usage")[0] == "CPU_USAGE"
    assert _action("ram usage")[0] == "RAM_USAGE"


def test_pomodoro_plugin_routes():
    assert _action("start pomodoro")[0] == "POMODORO_START"
    assert _action("pomodoro status")[0] == "POMODORO_STATUS"
    assert _action("stop pomodoro")[0] == "POMODORO_STOP"


def test_notes_plugin_routes():
    action, result = _action("new note check the manifest validator")
    assert action == "NEW_NOTE"
    assert result["args"]["text"] == "check the manifest validator"

    action, result = _action("search notes for manifest validator")
    assert action == "SEARCH_NOTES"
    assert result["args"]["query"] == "manifest validator"

    assert _action("list notes")[0] == "LIST_NOTES"


def test_smart_home_plugin_route():
    action, result = _action("smart home turn on desk lamp")
    assert action == "SMART_HOME"
    assert result["args"]["command"] == "turn on desk lamp"


def test_generic_search_still_goes_to_browser_not_plugin():
    action, result = _action("search for python pathlib examples")
    assert action == "OPEN_BROWSER"
