"""Locks on "what was the last message you sent" answering about THIS session,
with the message in it.

Observed live at 2.1.96. Asked at 17:32, ELI reported route_action
PERSONAL_MEMORY_DEEP_EXPLAIN with agents memory/system/orchestrator — a turn
that never happened in that session. Its saved_at was 15:46:36: 106 minutes and
one application restart earlier, from a session already closed.

Three faults stacked:

1. `last_trace.json` is one file that outlives the process, and nothing marked
   which run wrote it.
2. Request ids restart at req-000001 every session, so the stale payload was
   indistinguishable from a live one by id — it even collided exactly.
3. Every ordinary GUI turn is a STREAMED chat, and the streaming path never
   persisted a trace at all. engine.py:13196 already says so in prose: "an
   output guard in _finalize_chat_result (streaming never reaches it)". So the
   newest trace on disk was whatever non-streamed action last ran, at any point
   in history.

And underneath all three: the trace recorded `response_chars` but never the
response, so the question could not be answered even with a correct trace.
"""
import json
import os

import pytest

from eli.runtime import last_trace as lt
from eli.runtime.control_contracts import _trace_text


@pytest.fixture(autouse=True)
def isolated_trace(tmp_path, monkeypatch):
    target = tmp_path / "last_trace.json"
    monkeypatch.setattr(lt, "trace_path", lambda: target)
    yield target


# ── session scoping ─────────────────────────────────────────────────────────
def test_a_trace_from_this_run_is_returned():
    lt.save_last_trace({"route_action": "CHAT", "response_text": "hello"})
    assert lt.load_last_trace().get("response_text") == "hello"


def test_a_trace_from_a_previous_run_is_treated_as_absent(isolated_trace):
    """The live failure: a closed session's turn reported as 'your last response'."""
    lt.save_last_trace({"route_action": "PERSONAL_MEMORY_DEEP_EXPLAIN"})
    data = json.loads(isolated_trace.read_text())
    data["session_pid"] = os.getpid() + 99_999          # as if another run wrote it
    isolated_trace.write_text(json.dumps(data))

    assert lt.load_last_trace() == {}, "stale cross-session trace served as current"


def test_a_trace_with_no_session_marker_is_treated_as_absent(isolated_trace):
    """Files written before this fix carry no session_pid and must not be trusted."""
    isolated_trace.write_text(json.dumps({"route_action": "SELF_REPORT"}))
    assert lt.load_last_trace() == {}


def test_any_session_can_still_read_it_for_diagnostics(isolated_trace):
    lt.save_last_trace({"route_action": "CHAT"})
    data = json.loads(isolated_trace.read_text())
    data["session_pid"] = os.getpid() + 99_999
    isolated_trace.write_text(json.dumps(data))

    assert lt.load_last_trace(any_session=True).get("route_action") == "CHAT"


def test_missing_and_corrupt_files_are_survivable(isolated_trace):
    assert lt.load_last_trace() == {}
    isolated_trace.write_text("{not json")
    assert lt.load_last_trace() == {}


def test_saving_stamps_the_session():
    p = lt.save_last_trace({"route_action": "CHAT"})
    assert json.loads(p.read_text())["session_pid"] == os.getpid()


# ── the report says what the message WAS ────────────────────────────────────
def _trace(**over):
    base = {
        "request_id": "req-000003", "route_action": "CHAT", "result_action": "CHAT",
        "confidence": 0.84, "confidence_label": "high", "grounding_confidence": 0.59,
        "agents_used": ["memory", "orchestrator"], "plan": "none",
        "evidence_used": True, "grounded": True,
        "response_text": "You're right—no need to correct you.",
        "response_truncated": False,
        "user_input": "I spelt it right, there is no need to correct me",
    }
    base.update(over)
    return base


def test_the_message_is_quoted():
    out = _trace_text(_trace())
    assert "You're right—no need to correct you." in out


def test_the_message_comes_before_the_telemetry():
    """It answered with request ids and confidence scores and never said what the
    message was. The answer leads; the trace supports it."""
    out = _trace_text(_trace())
    assert out.index("You're right") < out.index("request_id")


def test_what_it_was_replying_to_is_shown():
    assert "I spelt it right" in _trace_text(_trace())


def test_truncation_is_marked_not_silent():
    out = _trace_text(_trace(response_text="a" * 50, response_truncated=True))
    assert "…" in out


def test_telemetry_is_still_present():
    """The trace block is still wanted — it just is not the whole answer."""
    out = _trace_text(_trace())
    for field in ("request_id", "agents_used", "grounding_confidence"):
        assert field in out


def test_a_trace_without_text_still_renders():
    """Traces written by paths that do not carry the reply must not crash the
    report — they just cannot lead with a quote."""
    out = _trace_text(_trace(response_text="", user_input=""))
    assert "Previous-response trace evidence:" in out
    assert "Last message I sent:" not in out


def test_no_trace_says_so_rather_than_inventing_one():
    assert "trace_available: false" in _trace_text({})


# ── the streaming path must persist ─────────────────────────────────────────
def test_streaming_path_persists_the_trace():
    """The actual bug. Every ordinary GUI turn streams, and that path only ever
    set the in-memory badge (_last_request_meta) — last_trace.json was never
    written, so 'last response' resolved to some older non-streamed action."""
    import inspect

    from eli.kernel import engine

    src = inspect.getsource(engine.CognitiveEngine._stream_chat)
    assert "save_last_trace" in src, \
        "streamed replies still do not persist a trace"
    assert "response_text" in src, \
        "streamed traces do not carry the reply text"


def test_publish_records_the_response_text():
    import inspect

    from eli.kernel import engine

    src = inspect.getsource(engine.CognitiveEngine._publish_last_response_meta)
    assert '"response_text"' in src
    assert '"user_input"' in src, "the trace cannot say what it was answering"
