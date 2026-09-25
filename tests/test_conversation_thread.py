from __future__ import annotations

from unittest.mock import patch

from eli.execution.router_enhanced import route
from eli.runtime.conversation_thread import (
    build_thread_aware_query,
    expand_web_query,
    extract_search_subject,
    extract_thread_topic,
    proactive_web_intent,
    set_route_context,
    should_proactive_web_search,
    web_query_has_substance,
)


def test_extract_thread_topic_dead_city():
    turns = [
        {"role": "user", "content": "I'm watching Blue Harbor blue harbor"},
        {"role": "assistant", "content": "Nice spinoff."},
    ]
    assert "blue harbor" in extract_thread_topic(turns).lower()


def test_expand_season_reviews_with_topic():
    q = expand_web_query(
        "some reviews for season 3",
        "Blue Harbor Season Two",
    )
    assert "blue harbor" in q.lower()
    assert "season 3" in q.lower()


def test_proactive_web_on_grounding_demand():
    turns = [
        {"role": "user", "content": "we're on Blue Harbor season 3"},
        {"role": "assistant", "content": "Juliette found the door."},
    ]
    ok, query, reason = should_proactive_web_search(
        "if you are so curious search the web and come with some facts",
        turns,
    )
    assert ok
    assert reason in ("grounding_demand", "explicit_web")
    assert "blue harbor" in query.lower()


def test_proactive_web_season_reviews_followup():
    turns = [
        {"role": "user", "content": "watching Blue Harbor with me"},
    ]
    ok, query, reason = should_proactive_web_search(
        "wanna do a web search and get some reviews for season 3",
        turns,
    )
    assert ok
    assert reason in ("thread_underspecified", "explicit_web")
    assert "blue harbor" in query.lower()
    assert "season 3" in query.lower()


@patch("eli.core.config.network_allowed", lambda: True)
def test_router_web_query_uses_thread_context():
    set_route_context(thread_topic="Blue Harbor Season Two")
    r = route("wanna do a web search and get some reviews for season 3")
    assert r["action"] == "WEB_SEARCH"
    q = (r.get("args") or {}).get("query", "")
    assert "blue harbor" in q.lower()
    assert "season 3" in q.lower()


def test_extract_search_subject_mid_sentence():
    subj = extract_search_subject(
        "damn straight, wanna do a web search and get some reviews for season 3"
    )
    assert "season 3" in subj.lower()


def test_build_thread_aware_query():
    turns = [{"role": "user", "content": "Blue Harbor season 3"}]
    q = build_thread_aware_query("reviews for season 3", turns)
    assert "blue harbor" in q.lower()


def test_web_query_has_substance():
    assert web_query_has_substance("Blue Harbor season 3 reviews")
    assert not web_query_has_substance("do a web search")
    assert not web_query_has_substance("look it up")
