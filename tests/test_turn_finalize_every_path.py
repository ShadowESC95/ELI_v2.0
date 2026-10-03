"""Stage 12 runs for every turn, however _process_impl exits.

Blueprint (orchestration_and_agents.md): "Stage 12 side effects (store the
turn, publish meta, _learn_from_result) run through ... one entry point for
every CHAT exit." The code didn't: the orchestrator path, which answers every
non-phatic CHAT turn, never stored ELI's reply, and middleware answers stored
nothing. A week of real use had 165 user turns and 103 replies. Nested turns
did the opposite: a multi-question split stored each fragment as something the
user typed, and a followthrough re-run stored ELI's own "fetch the latest news"
clause as a user turn.

process() now completes whatever a top-level turn didn't do, once, when it ends
normally. Nested turns store nothing; their parent stores the real message and
the reply the user saw.
"""
from unittest.mock import patch

import pytest

from eli.kernel.engine import MAIN_REPLY_DONE_SENTINEL, CognitiveEngine


class _Memory:
    def __init__(self):
        self.turns = []

    def add_conversation_turn(self, role, text, session_id, user_id):
        self.turns.append((role, text, session_id, user_id))


@pytest.fixture()
def eng(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_ORCHESTRATOR_AUDIT_DB", str(tmp_path / "orch.sqlite3"))
    e = CognitiveEngine.__new__(CognitiveEngine)
    e._fallback_session_id, e._fallback_user_id = "s-1", "u-1"
    e.memory = _Memory()
    e._episodic = []
    monkeypatch.setattr(CognitiveEngine, "_maybe_store_memory",
                        lambda self, text, role="user": self._episodic.append((role, text)))
    return e


def _roles(e):
    return [(r, t) for r, t, _, _ in e.memory.turns]


def _run(e, impl, *args, **kwargs):
    with patch.object(CognitiveEngine, "_process_impl", impl):
        out = e.process(*args, **kwargs)
        if hasattr(out, "__next__"):
            out = list(out)
    return out


def test_a_middleware_answer_stores_both_turns_in_order(eng):
    _run(eng, lambda self, *a, **k: "Current reasoning mode: quick.",
         "what reasoning mode are you in", user_id="alice", session_id="s-a")
    assert eng.memory.turns == [
        ("user", "what reasoning mode are you in", "s-a", "alice"),
        ("assistant", "Current reasoning mode: quick.", "s-a", "alice"),
    ]


def test_an_orchestrator_stream_reply_is_stored(eng):
    def impl(self, user_input, *a, **k):
        self._store_user_turn(user_input)  # the pipeline's own early store

        def g():
            yield "Crisp as "
            yield "a fresh compile."
            yield MAIN_REPLY_DONE_SENTINEL
        return g()

    _run(eng, impl, "how is the head?", stream=True)
    assert _roles(eng) == [("user", "how is the head?"),
                           ("assistant", "Crisp as a fresh compile.")]


def test_a_turn_that_stored_its_own_reply_is_not_stored_twice(eng):
    def impl(self, user_input, *a, **k):
        self._store_user_turn(user_input)
        self._store_assistant_turn("Opened app: Spotify")
        return {"ok": True, "action": "OPEN_APP", "content": "Opened app: Spotify"}

    _run(eng, impl, "open spotify")
    assert _roles(eng) == [("user", "open spotify"), ("assistant", "Opened app: Spotify")]


def test_a_split_message_is_stored_once_as_the_user_typed_it(eng):
    msg = "what is the capital of peru? and who won the match yesterday?"

    def impl(self, user_input, *a, **k):
        if user_input == msg:
            parts = [self.process("what is the capital of peru?"),
                     self.process("who won the match yesterday?")]
            return "\n\n".join(p["content"] for p in parts)
        self._store_user_turn(user_input)  # children behave like real turns
        self._store_assistant_turn(f"answer to {user_input}")
        return {"ok": True, "action": "CHAT", "content": f"answer to {user_input}"}

    _run(eng, impl, msg)
    # The store-time governor folds paragraph breaks into spaces.
    assert [(r, " ".join(t.split())) for r, t in _roles(eng)] == [
        ("user", msg),
        ("assistant", "answer to what is the capital of peru? "
                      "answer to who won the match yesterday?"),
    ]


def test_a_followthrough_rerun_never_becomes_a_user_turn(eng):
    def impl(self, user_input, *a, **k):
        if user_input == "anything new today?":
            def reply():
                yield "Sure. Let me check the news for you."
            return self._stream_with_followthrough(reply(), user_input)
        # The re-run: a real turn would store both sides of itself.
        self._store_user_turn(user_input)
        self._store_assistant_turn("Headline A")
        return {"ok": True, "action": "NEWS_FETCH", "content": "Headline A"}

    _run(eng, impl, "anything new today?", stream=True)
    assert _roles(eng) == [
        ("user", "anything new today?"),
        ("assistant", "Sure. Let me check the news for you."),
        ("assistant", "Headline A"),
    ]


def test_fragment_guard_and_autonomous_turns_store_nothing(eng):
    _run(eng, lambda self, *a, **k: {"ok": True, "action": "NOOP", "content": "{}"}, "and")
    _run(eng, lambda self, *a, **k: "Morning report ready.", "morning report", source="habit")
    assert eng.memory.turns == []


def test_a_turn_that_failed_is_not_finalized(eng):
    def boom(self, *a, **k):
        raise RuntimeError("model crashed")

    with pytest.raises(RuntimeError):
        _run(eng, boom, "hello")
    assert eng.memory.turns == []


def test_a_cancelled_stream_is_not_finalized(eng):
    def impl(self, *a, **k):
        def g():
            yield "partial"
            yield "rest"
        return g()

    with patch.object(CognitiveEngine, "_process_impl", impl):
        gen = eng.process("hi", stream=True)
        next(gen)
        gen.close()
    assert eng.memory.turns == []


def test_meta_is_published_for_a_turn_that_published_none(eng):
    eng._last_request_meta = {"action": "NEWS_FETCH", "response_text": "old turn"}
    _run(eng, lambda self, *a, **k: "Current reasoning mode: quick.", "what mode?")
    meta = eng._last_request_meta
    assert meta["response_text"] == "Current reasoning mode: quick."
    assert meta["user_input"] == "what mode?"
    assert meta["request_id"].startswith("req-")


def test_chat_like_turns_get_episodic_memory_and_actions_dont(eng):
    _run(eng, lambda self, *a, **k: "Fine, thanks.", "how are you")
    assert eng._episodic == [("user", "how are you"), ("assistant", "Fine, thanks.")]
    eng._episodic.clear()
    _run(eng, lambda self, *a, **k: {"ok": True, "action": "OPEN_APP", "content": "Opened."},
         "open firefox")
    assert eng._episodic == []


def test_a_turn_finalize_turn_already_handled_is_left_alone(eng):
    from eli.cognition.learning_coordinator import finalize_turn

    def impl(self, user_input, *a, **k):
        self._store_user_turn(user_input)
        finalize_turn(self, user_input=user_input, response="Done.",
                      intent={"action": "CHAT"}, result={"ok": True}, trace={})
        return {"ok": True, "action": "CHAT", "content": "Done."}

    with patch.object(CognitiveEngine, "_learn_from_result", lambda *a, **k: None):
        _run(eng, impl, "do the thing")
    assert _roles(eng) == [("user", "do the thing"), ("assistant", "Done.")]
    assert eng._episodic == []


# ── the splitter no longer cuts a challenge into separate turns ──────────────

class _ReachedPipeline(BaseException):
    pass


def test_a_challenge_with_several_question_marks_stays_one_turn():
    """The live message, verbatim. It was split three ways."""
    msg = ("Are you just saying that, or did you actually read the files.orchestrator etc.? "
           "or are you just providing made up nonsense again? Do you have timestamps for "
           "your error analysis in the previous message please")
    e = CognitiveEngine()
    real = e.process
    calls = []

    def counting(user_input, *a, **k):
        calls.append(user_input)
        return real(user_input, *a, **k) if len(calls) == 1 else {"content": "x"}

    e.process = counting
    with patch.object(CognitiveEngine, "_store_user_turn", side_effect=_ReachedPipeline):
        with pytest.raises(_ReachedPipeline):
            e.process(msg, stream=False)
    assert calls == [msg]


def test_a_nested_turn_does_not_capture_task_events_from_a_fragment(eng, tmp_path, monkeypatch):
    from eli.cognition.learning_coordinator import finalize_turn
    from eli.planning import goal_store as gs
    monkeypatch.setattr(gs, "goal_store_path", lambda: tmp_path / "goals.json")
    gs.open_task("Rebuild the tuner")
    fragment = "We decided to keep the scenarios deterministic and offline"

    def impl(self, user_input, *a, **k):
        if user_input == "outer":
            self.process(fragment)
            return "ok"
        finalize_turn(self, user_input=user_input, response="Done.",
                      intent={"action": "CHAT"}, result={"ok": True}, trace={})
        return {"ok": True, "action": "CHAT", "content": "Done."}

    with patch.object(CognitiveEngine, "_learn_from_result", lambda *a, **k: None):
        _run(eng, impl, "outer")
    assert "keep the scenarios deterministic" not in gs.task_brief()
