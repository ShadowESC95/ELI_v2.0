from __future__ import annotations

import pytest
from contextlib import ExitStack
from unittest.mock import patch

from eli.execution.router_enhanced import route


class _FakeBusResult:
    def __init__(self, action_result):
        self.action_result = action_result
        self.memory_context = "Bus memory context"
        self.aggregated_confidence = 0.98
        self.confidence_label = "very high"
        self.agents_used = ["system", "memory"]
        self.orchestrator_plan = "none"

    def to_context_block(self):
        return "Agent bus evidence block"


class _FakeBus:
    def __init__(self, result):
        self._result = result

    def dispatch(self, *_args, **_kwargs):
        return self._result


def _prepare_engine_for_synthesis_test(stack, action, action_result):
    from eli.cognition import agent_bus
    from eli.kernel import engine as engine_mod
    from eli.kernel.engine import CognitiveEngine

    eng = CognitiveEngine()
    eng._store_user_turn = lambda *_a, **_k: None
    eng._store_assistant_turn = lambda *_a, **_k: None
    eng._learn_from_result = lambda *_a, **_k: None
    eng._execute_post_actions = lambda *_a, **_k: None
    eng._parse_intent = lambda *_a, **_k: {"action": action, "args": {}, "confidence": 0.95, "meta": {}}
    stack.enter_context(patch.object(agent_bus, "get_bus", lambda: _FakeBus(_FakeBusResult(action_result))))

    def fail_if_executor_repeats(*_a, **_k):
        raise AssertionError("executor should not run again after AgentBus action_result")

    stack.enter_context(patch.object(engine_mod, "execute_action", fail_if_executor_repeats))
    return eng


def test_news_topic_is_preserved_for_physics_request():
    result = route("what's the latest news in physics")
    assert result["action"] == "NEWS_FETCH"
    assert result["args"].get("topic") == "physics"


def test_show_me_topic_news_does_not_route_as_file_read():
    result = route("show me physics news")
    assert result["action"] == "NEWS_FETCH"
    assert result["args"].get("topic") == "physics"


def test_news_topic_strips_politeness_tail():
    # "...for you" must not leak into the topic (was topic="you" / "hubble for you").
    r = route("get news about Hubble for me")
    assert r["action"] == "NEWS_FETCH"
    assert r["args"].get("topic") == "hubble"

    r2 = route("fetch me the news for you")
    assert r2["action"] == "NEWS_FETCH"
    assert not (r2["args"].get("topic") or "")   # general briefing, no junk topic


def test_deepen_query_routes_to_topic_news():
    # The follow-through rewrites a news deepen to this canonical form; it must
    # resolve to a topic-scoped NEWS_FETCH, not a general dump.
    r = route("fetch the latest news about Hubble")
    assert r["action"] == "NEWS_FETCH"
    assert r["args"].get("topic") == "hubble"


def test_relational_going_on_is_not_news():
    # Regression: "what's going on" aimed at ELI/the user must NOT detonate a
    # news fetch mid-conversation. (Live bug: "are you blaming that on me or
    # what's going on" → 55s NEWS_FETCH dump.)
    for t in [
        "are you blaming that on me or what's going on",
        "what's going on with you",
        "what's going on",
        "what's going on eli",
        "what's happening with the project",
    ]:
        assert route(t)["action"] != "NEWS_FETCH", f"false news on {t!r}"


def test_world_scoped_and_explicit_news_still_route():
    for t in [
        "what's happening in the world",
        "what's happening today",
        "what's the news",
        "latest news",
        "any news",
        "give me the headlines",
    ]:
        assert route(t)["action"] == "NEWS_FETCH", f"missed news on {t!r}"


def test_date_and_time_route_to_deterministic_tools():
    assert route("what's the date")["action"] == "DATE"
    assert route("what day is it")["action"] == "DATE"
    assert route("what time is it")["action"] == "TIME"


def test_browser_tab_controls_route_to_keyboard_shortcuts():
    next_tab = route("go to next tab in browser")
    close_tab = route("exit current tab")
    assert next_tab["action"] == "KEYBOARD"
    assert next_tab["args"]["key"] == "ctrl+tab"
    assert close_tab["action"] == "KEYBOARD"
    assert close_tab["args"]["key"] == "ctrl+w"


def test_browser_play_button_routes_to_browser_media_control():
    result = route("click play button in browser")
    assert result["action"] == "MEDIA_CONTROL"
    assert result["args"]["command"] == "play"
    assert result["args"]["target"] == "browser"


def test_play_specific_music_defaults_to_spotify_search_target():
    result = route("play soldiers logic by diabolic")
    assert result["action"] == "PLAY_MEDIA"
    assert result["args"]["query"] == "soldiers logic by diabolic"
    assert result["args"]["target"] == "spotify"


def test_play_specific_explicit_spotify_target_is_preserved():
    result = route("play soldiers logic by diabolic on spotify")
    assert result["action"] == "PLAY_MEDIA"
    assert result["args"]["query"] == "soldiers logic by diabolic"
    assert result["args"]["target"] == "spotify"


def test_play_specific_explicit_youtube_target_is_preserved():
    result = route("play soldiers logic by diabolic on youtube")
    assert result["action"] == "PLAY_MEDIA"
    assert result["args"]["query"] == "soldiers logic by diabolic"
    assert result["args"]["target"] == "youtube"


def test_play_specific_video_provider_targets_are_normalized():
    netflix = route("play Oppenheimer, on netflix")
    prime = route("play Oppenheimer on prime")

    assert netflix["action"] == "PLAY_MEDIA"
    assert netflix["args"]["query"] == "Oppenheimer"
    assert netflix["args"]["target"] == "netflix"
    assert prime["action"] == "PLAY_MEDIA"
    assert prime["args"]["query"] == "Oppenheimer"
    assert prime["args"]["target"] == "primevideo"


def test_find_text_on_screen_routes_to_screen_locator():
    result = route("find status label on the screen")
    assert result["action"] == "SCREEN_LOCATE"
    assert result["args"]["query"] == "status label"


def test_click_text_on_screen_routes_to_locator_click():
    result = route("click sign in on the screen")
    assert result["action"] == "SCREEN_LOCATE"
    assert result["args"]["query"] == "sign in"
    assert result["args"]["click"] is True


def test_read_screen_routes_to_screen_analysis_before_file_read():
    result = route("read the screen")
    assert result["action"] == "SCREEN_READ_ANALYZE"


def test_screen_locator_ranks_ocr_boxes_by_query():
    from eli.perception.screen_locator import _find_matches

    boxes = [
        {"text": "Home", "x": 10, "y": 10, "w": 40, "h": 20, "page": 1, "block": 1, "paragraph": 1, "line": 1, "word": 1},
        {"text": "Sign", "x": 100, "y": 20, "w": 38, "h": 20, "page": 1, "block": 1, "paragraph": 1, "line": 2, "word": 1},
        {"text": "In", "x": 142, "y": 20, "w": 18, "h": 20, "page": 1, "block": 1, "paragraph": 1, "line": 2, "word": 2},
        {"text": "Dashboard", "x": 300, "y": 30, "w": 90, "h": 24, "page": 1, "block": 1, "paragraph": 1, "line": 3, "word": 1},
    ]
    matches = _find_matches("sign in", boxes)
    assert matches
    assert matches[0]["text"].lower() == "sign in"
    assert matches[0]["cx"] == 130
    assert matches[0]["cy"] == 30


def test_arbitrary_resume_target_is_preserved_without_service_allowlist():
    result = route("resume classroom stream")
    assert result["action"] == "MEDIA_CONTROL"
    assert result["args"].get("command") == "play"
    assert result["args"].get("target") == "classroom stream"
    assert result["args"].get("type") == "dynamic"


def test_arbitrary_pause_target_is_preserved_without_service_allowlist():
    result = route("pause remote lesson")
    assert result["action"] == "MEDIA_CONTROL"
    assert result["args"].get("command") == "pause"
    assert result["args"].get("target") == "remote lesson"
    assert result["args"].get("type") == "dynamic"


def test_internal_prompt_echo_is_not_routed_as_media_search():
    result = route("play some the situation brief and conversation history")
    assert result["action"] == "CHAT"


def test_stt_internal_prompt_echo_is_ignored_before_dispatch():
    from eli.perception.audio_stt import VoiceGate

    gate = VoiceGate()
    state, command, wake = gate.classify("play some the situation brief and conversation history")
    assert state == "ignore"
    assert command is None
    assert wake is None


def test_stt_background_chat_is_ignored_without_wake_word():
    from eli.perception.audio_stt import VoiceGate

    gate = VoiceGate()
    state, command, wake = gate.classify("is lorikeets mean smaller we get it it's like i'm being punished for clarity")
    assert state == "ignore_unarmed"
    assert command is None
    assert wake is None


def test_stt_wake_word_still_allows_freeform_chat():
    from eli.perception.audio_stt import VoiceGate

    gate = VoiceGate()
    state, command, wake = gate.classify("computer is lorikeets mean smaller")
    assert state == "dispatch"
    assert command == "is lorikeets mean smaller"
    assert wake == "computer"


def test_news_relevance_filter_does_not_return_unrelated_hackernews(tmp_path):
    from eli.tools.news import news_fetcher

    db = tmp_path / "news.sqlite3"
    with patch.object(news_fetcher, "_get_db", lambda: db):
        fetcher = news_fetcher.NewsFetcher()
        fetcher._store([
            {
                "source": "HackerNews",
                "title": "Ghostty is leaving GitHub",
                "url": "https://example.test/hn",
                "summary": "Developer tooling story",
                "category": "tech",
            },
            {
                "source": "Physics World",
                "title": "Quantum sensor improves dark matter search",
                "url": "https://example.test/physics",
                "summary": "Particle physics researchers report a new detector result.",
                "category": "physics",
            },
        ])

        hits = fetcher.get_relevant("physics", limit=5)
    assert hits
    assert all("HackerNews" not in h["source"] for h in hits)
    assert any("Quantum sensor" in h["title"] for h in hits)


def test_agent_bus_preserves_failed_direct_media_result():
    from eli.cognition import agent_bus
    from eli.execution import executor_enhanced

    def fake_execute(action, args=None):
        return {
            "ok": False,
            "action": action,
            "error": "No media player running",
            "content": "No media player running",
            "response": "No media player running",
        }

    with patch.object(executor_enhanced, "execute", fake_execute), \
            patch.object(agent_bus, "_ALL_AGENTS", [agent_bus.SystemAgent()]):
        bus = agent_bus.AgentBus(max_workers=1)
        try:
            result = bus.dispatch(
                "play",
                {"action": "PLAY_MEDIA", "args": {}, "confidence": 0.88},
                session_id="test",
                user_id="test",
            )
        finally:
            bus.shutdown()

    assert result.action_result is not None
    assert result.action_result["ok"] is False
    assert result.action_result["response"] == "No media player running"


def test_command_action_result_is_synthesized_in_nonquick_mode():
    with ExitStack() as stack:
        eng = _prepare_engine_for_synthesis_test(
            stack,
            "NEWS_FETCH",
            {
                "ok": True,
                "action": "NEWS_FETCH",
                "content": "Live news raw executor evidence about physics.",
                "response": "Live news raw executor evidence about physics.",
            },
        )

        eng._synthesize_answer = lambda *_a, **_k: "I checked the live news evidence about physics."
        result = eng.process("what's the latest news in physics", reasoning_mode="chain_of_thought")

    content = result.get("content") if isinstance(result, dict) else result
    assert content == "I checked the live news evidence about physics."


def test_control_action_result_uses_full_pipeline_in_nonquick_mode():
    with ExitStack() as stack:
        eng = _prepare_engine_for_synthesis_test(
            stack,
            "RUNTIME_AUDIT",
            {
                "ok": True,
                "action": "RUNTIME_AUDIT",
                "content": "Runtime audit evidence: imports were checked.",
                "response": "Runtime audit evidence: imports were checked.",
            },
        )
        eng._run_chat_reasoning_loop = lambda **_k: {
            "response": "I checked the runtime audit evidence: imports were checked.",
            "score": 0.91,
            "threshold": 0.7,
            "clarified": False,
        }

        result = eng.process("run a full runtime audit", reasoning_mode="chain_of_thought")

    content = result.get("content") if isinstance(result, dict) else result
    assert content == "I checked the runtime audit evidence: imports were checked."


def test_explain_memory_runtime_is_verbatim_even_in_nonquick_mode():
    # Regression (Jason, 2026-06-06): in CoT mode, EXPLAIN_MEMORY_RUNTIME's
    # correct live DB audit was run through compact synthesis, which on the small
    # local model hallucinated a phantom "memory.sqlite3 for temporary storage"
    # and miscounted the databases. Deep technical introspection ("exactly how
    # the memory pipeline works") must return the grounded report VERBATIM in
    # every reasoning mode — synthesis can only corrupt grounded facts here.
    grounded = (
        "Memory runtime:\n- user_db: .../user.sqlite3\n- agent_db: .../agent.sqlite3\n"
        "SQLite tables observed live: conversation_turns(374), memories(156)..."
    )
    with ExitStack() as stack:
        eng = _prepare_engine_for_synthesis_test(
            stack,
            "EXPLAIN_MEMORY_RUNTIME",
            {
                "ok": True,
                "action": "EXPLAIN_MEMORY_RUNTIME",
                "content": grounded,
                "response": grounded,
                "evidence_source": "memory_runtime_sanitized",
            },
        )

        # If either synthesis surface is invoked for this action, fail loudly —
        # it must be bypassed.
        def _no_synth(*_a, **_k):
            raise AssertionError("EXPLAIN_MEMORY_RUNTIME must not be synthesized")

        eng._synthesize_answer = _no_synth
        eng._compact_grounded_synthesis = _no_synth
        eng._run_chat_reasoning_loop = _no_synth

        result = eng.process(
            "tell me exactly how your memory works — files, folders, processes",
            reasoning_mode="chain_of_thought",
        )

    assert isinstance(result, dict)
    assert result.get("content") == grounded
    # Must not invent a phantom database.
    assert "memory.sqlite3" not in result.get("content", "")


def test_runtime_status_quick_is_direct_nonquick_uses_full_pipeline():
    """Spec: Quick mode may return deterministic live runtime evidence directly.
    Non-Quick modes must run the full cognition pipeline and synthesize via the
    LLM — they must never return executor/evidence packets verbatim. Under test
    mode (no GGUF loaded), non-Quick correctly fails closed rather than leaking
    raw telemetry; the assertion validates the V19 surface contract, not the
    synthesized content (which can only be checked with a live model).
    """
    from eli.kernel.engine import CognitiveEngine

    def surface_text(value):
        if isinstance(value, dict):
            return (
                value.get("content")
                or value.get("response")
                or value.get("text")
                or str(value)
            )
        return str(value)

    quick_engine = CognitiveEngine()
    quick_result = quick_engine.process(
        "Who are you and what are you actually running on right now — model, context size, GPU layers, everything.",
        reasoning_mode="quick",
    )
    quick_text = surface_text(quick_result)
    assert "ELI" in quick_text
    assert (
        "runtime_truth_evidence" in quick_text
        or "Runtime status" in quick_text
        or "Running model:" in quick_text
        or "effective ctx=" in quick_text
    )

    nonquick_engine = CognitiveEngine()
    nonquick_result = nonquick_engine.process(
        "Who are you and what are you actually running on right now — model, context size, GPU layers, everything.",
        reasoning_mode="constitutional_ai",
    )

    # V19 contract: non-Quick is a structured RUNTIME_STATUS dict, never raw evidence.
    assert isinstance(nonquick_result, dict)
    assert nonquick_result.get("action") == "RUNTIME_STATUS"

    source = str(nonquick_result.get("source") or "")
    assert source.startswith("runtime_status_nonquick_full_pipeline"), (
        f"non-Quick must take the V19 full-pipeline path; got source={source!r}"
    )

    # Must not be the legacy V8 raw-evidence surface.
    assert nonquick_result.get("evidence_source") != "runtime_status_grounded_dynamic_evidence_v8"

    report = nonquick_result.get("report") or {}
    assert report.get("quick_direct_allowed") is False
    assert report.get("direct_telemetry_returned") is False

    # Under live GGUF, synthesis_validated should be True and content should mention
    # runtime terms. Under test mode (no model loaded), synthesis fails closed and
    # synthesis_validated is False — both states are spec-compliant.
    if report.get("synthesis_validated") is True:
        synthesized = surface_text(nonquick_result).lower()
        runtime_terms = ("model", "context", "gpu", "provider", "runtime")
        assert sum(1 for t in runtime_terms if t in synthesized) >= 3, (
            f"synthesized non-Quick text missing runtime terms: {synthesized[:200]!r}"
        )

def test_gguf_stream_keeps_global_llm_lock_during_iteration():
    from eli.cognition import gguf_inference

    owns_lock = getattr(gguf_inference._LLM_CALL_LOCK, "_is_owned", None)
    if owns_lock is None:
        pytest.skip("RLock ownership introspection unavailable")

    observed = []

    def fake_llm(*_args, **kwargs):
        assert kwargs["stream"] is True

        def chunks():
            observed.append(bool(owns_lock()))
            yield {"choices": [{"text": "ok"}]}

        return chunks()

    stream = gguf_inference._safe_invoke_llm(
        fake_llm,
        "prompt",
        temperature=0.0,
        max_tokens=16,
        top_p=1.0,
        top_k=40,
        repeat_penalty=1.0,
        stop=[],
        stream=True,
        grammar=None,
    )

    assert observed == []
    assert [chunk["choices"][0]["text"] for chunk in stream] == ["ok"]
    assert observed == [True]
    assert owns_lock() is False
