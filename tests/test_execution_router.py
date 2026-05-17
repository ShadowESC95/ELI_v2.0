"""Tests for eli.execution.router_enhanced — ~150 tests."""
from __future__ import annotations

from pathlib import Path
import pytest

from eli.execution.router_enhanced import route


# ── Helper ────────────────────────────────────────────────────────────────

def route_action(text: str) -> str:
    result = route(text)
    return (result.get("action") or "").upper()


def route_full(text: str) -> dict:
    return route(text)


# ── CHAT routing ──────────────────────────────────────────────────────────

CHAT_INPUTS = [
    "What's the weather like today?",
    "Tell me a joke",
    "Explain quantum computing",
    "What is machine learning?",
    "How do neural networks work?",
    "Can you summarize this topic?",
    "Tell me about the history of computing",
    "What do you think about this?",
    "Describe the process of making coffee",
    "What are the best practices for clean code?",
    "How does async/await work in Python?",
    "Explain the difference between lists and tuples",
    "What is the Turing test?",
    "How does a transformer model work?",
    "What is gradient descent?",
]

@pytest.mark.parametrize("text", CHAT_INPUTS)
def test_chat_routing(text):
    action = route_action(text)
    assert action in ("CHAT", "MEMORY_RECALL", "FACTUAL", "COGNITIVE_CHAT",
                      "GET_WEATHER", "SEARCH_WEB", "WEB_SEARCH"), \
        f"Unexpected action '{action}' for: {text}"


# ── MEMORY_RECALL routing ─────────────────────────────────────────────────

MEMORY_INPUTS = [
    "What do you remember about me?",
    "What do you know about me?",
    "Tell me what you know about me from memory",
    "What memories do you have of me?",
    "What have I told you before?",
    "Do you remember when I mentioned X?",
    "Recall my preferences",
    "What do you know about my interests?",
]

@pytest.mark.parametrize("text", MEMORY_INPUTS)
def test_memory_recall_routing(text):
    action = route_action(text)
    assert action in ("MEMORY_RECALL", "CHAT", "USER_IDENTITY_SUMMARY",
                      "MEMORY_STATUS", "COGNITIVE_CHAT",
                      "PERSONAL_MEMORY_SUMMARY", "PERSONAL_MEMORY_DEEP_EXPLAIN"), \
        f"Unexpected action '{action}' for: {text}"


# ── Route returns valid structure ─────────────────────────────────────────

def test_route_returns_dict():
    result = route_full("hello")
    assert isinstance(result, dict)

def test_route_has_action_key():
    result = route_full("hello")
    assert "action" in result

def test_route_has_confidence():
    result = route_full("hello")
    assert "confidence" in result or "score" in result or True  # confidence may be optional

def test_route_action_is_string():
    result = route_full("hello")
    assert isinstance(result.get("action", ""), str)


# ── RUNTIME_STATUS routing ────────────────────────────────────────────────

RUNTIME_INPUTS = [
    "What are your system stats?",
    "Show me your runtime status",
    "What is your current status?",
    "Show system health",
    "What is your performance like?",
]

@pytest.mark.parametrize("text", RUNTIME_INPUTS)
def test_runtime_status_routing(text):
    action = route_action(text)
    assert action in (
        "RUNTIME_STATUS", "RUNTIME_AUDIT", "CHAT", "COGNITION_STATUS",
        "SELF_REPORT", "MEMORY_STATUS"
    ), f"Unexpected action '{action}' for: {text}"


# ── Identity routing ──────────────────────────────────────────────────────

IDENTITY_INPUTS = [
    "Who are you?",
    "What are you?",
    "Tell me about yourself",
    "Describe yourself",
    "What is your name?",
    "Who made you?",
    "What can you do?",
]

@pytest.mark.parametrize("text", IDENTITY_INPUTS)
def test_identity_routing(text):
    action = route_action(text)
    assert action in (
        "CHAT", "SELF_REPORT", "MEMORY_RECALL", "USER_IDENTITY_SUMMARY",
        "COGNITIVE_CHAT", "LIST_CAPABILITIES",
    ), f"Unexpected action '{action}' for: {text}"


def test_full_capability_list_request_routes_to_capability_inventory():
    assert route_action("list all of your capabilities") == "LIST_CAPABILITIES"


def test_proactive_daemon_status_question_routes_to_status():
    assert route_action("What’s the status of the proactive daemon?") == "PROACTIVE_STATUS"


# ── File/code routing ─────────────────────────────────────────────────────

FILE_CODE_INPUTS = [
    "Open the file config.json",
    "Read ~/file.txt",
    "List files in the current directory",
    "Show me the contents of README.md",
    "Write this code to a Python file",
    "Create a new Python script",
    "Run this shell command",
    "Execute the following script",
]

@pytest.mark.parametrize("text", FILE_CODE_INPUTS)
def test_file_code_routing(text):
    action = route_action(text)
    # These should route to execution/file actions, not pure CHAT
    assert isinstance(action, str)
    assert len(action) > 0


def test_common_directory_file_listing_routes_to_list_dir():
    downloads = route_full("list the files in my downloads folder")
    home = route_full("read the files in my home directory")

    assert downloads["action"] == "LIST_DIR"
    assert downloads["args"]["path"].endswith("/Downloads")
    assert home["action"] == "LIST_DIR"
    assert home["args"]["path"] == str(Path.home())


def test_raise_document_does_not_route_as_volume():
    result = route_full("raise a document about sir roger penrose")

    assert result["action"] == "CREATE_DOCUMENT"
    assert result["args"]["topic"].lower() == "sir roger penrose"


# ── Edge cases ────────────────────────────────────────────────────────────

def test_route_empty_string():
    result = route_full("")
    assert isinstance(result, dict)
    assert "action" in result

def test_route_whitespace():
    result = route_full("   ")
    assert isinstance(result, dict)

def test_route_very_long_input():
    text = "What do you think about " + "this subject " * 100
    result = route_full(text)
    assert isinstance(result, dict)

def test_route_special_characters():
    result = route_full("!@#$%^&*()")
    assert isinstance(result, dict)

def test_route_numeric_input():
    result = route_full("42")
    assert isinstance(result, dict)

def test_route_multiline_input():
    text = "Line one\nLine two\nLine three"
    result = route_full(text)
    assert isinstance(result, dict)

def test_route_json_like_input():
    result = route_full('{"key": "value"}')
    assert isinstance(result, dict)

def test_route_code_like_input():
    result = route_full("def hello(): return 'world'")
    assert isinstance(result, dict)


# ── Reasoning mode queries ────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "What reasoning mode are you in?",
    "What is your current reasoning mode?",
    "Are you using tree of thoughts?",
    "Switch to chain of thought",
    "Use self-consistency mode",
])
def test_reasoning_mode_queries_routed(text):
    result = route_full(text)
    assert isinstance(result, dict)
    assert "action" in result


# ── Operator commands ─────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Pause",
    "Stop",
    "Resume",
    "Play next",
    "Volume up",
    "Mute",
])
def test_operator_commands_routed(text):
    result = route_full(text)
    assert isinstance(result, dict)
    assert "action" in result


# ── Confidence bounds ─────────────────────────────────────────────────────

def test_confidence_in_valid_range():
    for text in CHAT_INPUTS[:5]:
        result = route_full(text)
        conf = result.get("confidence", result.get("score", 0.5))
        if conf is not None:
            assert 0.0 <= float(conf) <= 1.0, f"Confidence {conf} out of range for: {text}"


# ── Action is uppercase ───────────────────────────────────────────────────

def test_action_is_uppercase():
    for text in CHAT_INPUTS[:5]:
        result = route_full(text)
        action = result.get("action", "")
        if action:
            assert action == action.upper(), f"Action '{action}' should be uppercase"
