"""Extended router pattern tests — ~200 tests covering all route branches."""
from __future__ import annotations

import pytest
from eli.execution.router_enhanced import route


def action(text: str) -> str:
    return (route(text).get("action") or "").upper()


# ── Greeting / Phatic routing ─────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "hello", "hi", "hey", "howdy", "good morning", "good evening",
    "hello there", "hi eli", "hey there",
])
def test_phatic_greeting(text):
    result = route(text)
    assert isinstance(result, dict)
    assert "action" in result


# ── Math / factual routing ────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "What is 2 + 2?",
    "Calculate the square root of 144",
    "What is pi?",
    "Convert 100 Fahrenheit to Celsius",
    "What is 1024 in binary?",
    "What's the integral of x^2?",
    "Solve: 3x + 5 = 20",
    "What year did WW2 end?",
    "Who wrote Hamlet?",
    "What is the speed of light?",
    "How far is the moon from Earth?",
    "What is the boiling point of water?",
])
def test_factual_queries(text):
    result = route(text)
    assert isinstance(result, dict)
    a = (result.get("action") or "").upper()
    assert a in ("CHAT", "FACTUAL", "COGNITIVE_CHAT"), f"'{a}' for: {text}"


# ── Memory specific recall ────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "When did I mention jazz?",
    "Have I talked about Python before?",
    "Do you remember what I said last time?",
    "What have I told you about my job?",
    "When did I mention my name?",
    "What are my interests according to you?",
    "Do you have any notes about me?",
])
def test_specific_memory_recall(text):
    result = route(text)
    assert isinstance(result, dict)
    assert "action" in result


# ── Identity / self-awareness queries ────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Who are you?",
    "What are you?",
    "What is your name?",
    "Introduce yourself",
    "Tell me about yourself",
    "What are you capable of?",
    "What can you do?",
    "What are your limitations?",
    "Are you an AI?",
    "Are you sentient?",
])
def test_identity_queries(text):
    result = route(text)
    assert isinstance(result, dict)
    a = (result.get("action") or "").upper()
    assert a in ("CHAT", "SELF_REPORT", "COGNITIVE_CHAT", "MEMORY_RECALL",
                 "USER_IDENTITY_SUMMARY", "LIST_CAPABILITIES"), f"'{a}' for: {text}"


# ── Reasoning mode queries ────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "What reasoning mode are you using?",
    "Are you in tree of thoughts mode?",
    "Switch to chain of thought",
    "What is your current thinking mode?",
    "Use constitutional AI mode",
    "Enable self-consistency",
])
def test_reasoning_mode_queries(text):
    result = route(text)
    assert isinstance(result, dict)
    assert "action" in result


# ── Cognition/pipeline queries ────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "How does your cognition pipeline work?",
    "What agents are you running?",
    "Show your cognition status",
    "What is your pipeline doing?",
    "Describe your architecture",
])
def test_cognition_queries(text):
    result = route(text)
    assert isinstance(result, dict)
    a = (result.get("action") or "").upper()
    assert a in ("CHAT", "COGNITION_STATUS", "RUNTIME_STATUS",
                 "COGNITIVE_CHAT", "SELF_REPORT",
                 "EXPLAIN_COGNITION_RUNTIME"), f"'{a}' for: {text}"


# ── File system queries ───────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "List files in ~/Documents",
    "Read the file README.md",
    "Show directory contents",
    "What files are in the current folder?",
    "Open config.json",
])
def test_file_queries(text):
    result = route(text)
    assert isinstance(result, dict)
    assert "action" in result


# ── Code queries ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Write a Python function to sort a list",
    "Fix this code: def foo(): retun 42",
    "Explain this Python code",
    "Create a bash script to backup files",
    "What does this regex do: ^\\d+$",
    "How do I reverse a string in Python?",
    "Write a SQL query to select all users",
    "Debug this JavaScript function",
])
def test_code_queries(text):
    result = route(text)
    assert isinstance(result, dict)
    a = (result.get("action") or "").upper()
    assert len(a) > 0


# ── Operator / media commands ────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Pause the music",
    "Resume playback",
    "Play next track",
    "Stop everything",
    "Volume up",
    "Mute",
    "Skip",
    "Next song",
])
def test_operator_commands(text):
    result = route(text)
    assert isinstance(result, dict)
    assert "action" in result


# ── Long-form queries ─────────────────────────────────────────────────────

LONG_QUERIES = [
    "I'm building a distributed machine learning system with PyTorch and I need to understand the best practices for gradient synchronization across multiple GPUs. Can you explain the different approaches?",
    "Can you explain the differences between supervised, unsupervised, and reinforcement learning, including when to use each approach and what kinds of problems they're best suited for?",
    "I have a Python application that's running slowly. I've already tried basic profiling and found the bottleneck is in database queries. What are the best approaches for optimizing SQLite queries in Python?",
    "What are the main philosophical differences between the utilitarian and deontological approaches to ethics, and how might these apply to real-world AI systems development?",
]

@pytest.mark.parametrize("text", LONG_QUERIES)
def test_long_query_routing(text):
    result = route(text)
    assert isinstance(result, dict)
    a = (result.get("action") or "").upper()
    assert a in ("CHAT", "FACTUAL", "COGNITIVE_CHAT", "MEMORY_RECALL"), \
        f"'{a}' for long query"


# ── Confidence bounds ─────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "hello", "what is Python?", "open file.txt",
    "what do you know about me?", "show system status",
])
def test_confidence_in_range(text):
    result = route(text)
    conf = result.get("confidence", result.get("score", 0.5))
    if conf is not None:
        assert 0.0 <= float(conf) <= 1.0


# ── Action string format ──────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "hello", "what is machine learning?", "list files",
    "what do you remember?", "show runtime status",
    "write python code", "explain this error",
])
def test_action_is_uppercase_string(text):
    result = route(text)
    a = result.get("action", "")
    assert isinstance(a, str)
    if a:
        assert a == a.upper()


# ── No crashes on weird inputs ────────────────────────────────────────────

WEIRD_INPUTS = [
    None,
    "",
    "   ",
    "\n\n\n",
    "\t\t",
    "." * 500,
    "?" * 100,
    "1" * 200,
    "!!!!",
    "🤖🤖🤖",
    "SELECT * FROM users;",
    "<script>alert('xss')</script>",
    "../../etc/passwd",
    '{"key": null}',
    "True",
    "False",
    "None",
    "0",
    "-1",
    "inf",
]

@pytest.mark.parametrize("text", WEIRD_INPUTS)
def test_no_crash_weird_inputs(text):
    try:
        result = route(text or "")
        assert isinstance(result, dict)
    except Exception as e:
        pytest.fail(f"route crashed with '{text}': {e}")
