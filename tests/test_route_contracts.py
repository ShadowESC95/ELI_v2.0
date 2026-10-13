from __future__ import annotations


def test_hybrid_memory_question_classifies_as_personal_deep_explain():
    from eli.execution.route_contracts import classify_precedence_route

    r = classify_precedence_route(
        "Explain exactly how your memory system works internally — which files, "
        "which DB tables, which functions and what you actually remember about me. "
        "We are not in quick mode."
    )

    assert r is not None
    assert r["action"] == "PERSONAL_MEMORY_DEEP_EXPLAIN"
    assert r["meta"]["task_family"] == "personal_memory"


def test_pure_memory_internals_not_stolen_by_personal_deep_contract():
    from eli.execution.route_contracts import classify_precedence_route

    r = classify_precedence_route(
        "Explain exactly how your memory system works internally — which files, which DB tables, which functions."
    )

    assert r is None


def test_pure_personal_memory_not_stolen_by_hybrid_contract():
    from eli.execution.route_contracts import classify_precedence_route

    r = classify_precedence_route(
        "What do you know about me from memory? Give me everything."
    )

    assert r is None


def test_user_model_provenance_static_vs_dynamic():
    from eli.execution.route_contracts import (
        classify_precedence_route,
        wants_user_model_provenance,
    )

    text = (
        "Is the about me section hardcoded or does your understanding of me evolve?"
    )
    assert wants_user_model_provenance(text)
    r = classify_precedence_route(text)
    assert r is not None
    assert r["action"] == "PERSONAL_MEMORY_DEEP_EXPLAIN"


# ── what kind of thing an action is ──────────────────────────────────────────

def test_the_name_of_an_action_says_whether_it_changes_anything():
    from eli.execution.route_contracts import changes_something

    for name in ("OPEN_APP", "CLOSE_APP", "PLAY_MEDIA", "STOP_MEDIA", "MEDIA_CONTROL", "VOLUME", "SHELL_EXEC",
                 "OPEN_POWER_SETTINGS", "MAXIMISE_WINDOW", "CREATE_FILE", "SET_ALARM", "MEMORY_FORGET"):
        assert changes_something(name), name
    for name in ("NOW_PLAYING", "GET_WEATHER", "LIST_DIR", "READ_FILE", "MEMORY_RECALL", "WEB_SEARCH", "NEWS_FETCH",
                 "SELF_REPORT", "RUNTIME_STATUS", "EXPLAIN_LAST_RESPONSE", "ANALYZE_PDF_FOLDER", "CHAT", "NOOP", "", None):
        assert not changes_something(name), name


def test_the_engine_s_own_lists_agree_with_it():
    """Five sets in the engine each held part of this and had drifted (one lacked STOP_MEDIA)."""
    from eli.execution.route_contracts import changes_something
    from eli.kernel import engine

    assert all(changes_something(a) for a in engine._AUTHORITY_FAILCLOSED_ACTIONS)


def test_a_sentence_fits_its_action_when_it_tells_eli_to_do_it():
    from eli.execution.route_contracts import fits

    stop = {"action": "STOP_MEDIA", "args": {}, "meta": {"entities": {"target": "spotify"}}}
    assert fits("stop spotify", stop) and fits("could you stop spotify please", stop)
    assert not fits("you need to stop lying to me about spotify and giving false task updates and reports", stop)
    assert not fits("you did not stop spotify", stop)
    assert not fits("Spotify received that stop signal, paused the track, but left the app window open "
                    "because it was not told to quit", stop)
    assert fits("pause the music for a second while i take this call", {"action": "PAUSE_MEDIA", "args": {}})
    assert fits("purge stale context", {"action": "PERSONA_REFRESH", "args": {}}), "a rule's own phrasing need not name its action"
    # some sentence of the message has to be the instruction
    assert not fits("well done. you did not need to stop spotify though", stop)
    assert fits("well done. stop spotify", stop)
    # a rule may pass the whole message along for the executor to read the details from
    later = "delete background task for 02:00 on Sunday, August 2nd"
    assert fits(later, {"action": "CANCEL_TASK", "args": {"job_id": None, "text": later}})
    play = {"action": "PLAY_MEDIA", "args": {"query": "the long and winding road to nowhere in particular at all"}}
    assert fits("play the long and winding road to nowhere in particular at all", play), "its argument is its own words"
    assert fits("anything at all, however long, about whatever it may be and then some more words",
                {"action": "RUNTIME_STATUS", "args": {}}), "a reading action changes nothing"
