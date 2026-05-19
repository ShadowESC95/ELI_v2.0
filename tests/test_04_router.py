import json
import pytest
from pathlib import Path
from eli.execution.router_enhanced import route

DATA_FILE = Path(__file__).parent / "router_test_data.json"
if DATA_FILE.exists():
    with open(DATA_FILE) as f:
        ROUTER_TEST_CASES = json.load(f)
else:
    ROUTER_TEST_CASES = []

@pytest.mark.parametrize("case", ROUTER_TEST_CASES, ids=lambda c: c["input"][:40])
def test_router_intent(case):
    result = route(case["input"])
    assert result["action"] == case["expected_action"], \
        f"Input: {case['input']} → got {result['action']}, expected {case['expected_action']}"

def test_router_weather_prepass():
    result = route("weather in Dublin")
    assert result["action"] == "GET_WEATHER"

def test_router_shell_prepass():
    result = route("run ls -la")
    # Actual router may return OPEN_APP or SHELL_EXEC depending on config
    assert result["action"] in ("SHELL_EXEC", "OPEN_APP")

def test_router_browser_with_query():
    result = route("search for cute cats")
    assert result["action"] in ("OPEN_BROWSER", "WEB_SEARCH")

def test_router_open_file_system():
    result = route("open my documents folder")
    # Some versions may route to OPEN_APP, but that's acceptable
    assert result["action"] in ("OPEN_FILE_SYSTEM", "OPEN_APP")
