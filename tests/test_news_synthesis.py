"""News synthesis — pure helpers + the freshness/recency guarantees.

Covers the model-free logic of the news read: one-sentence gisting, cross-domain
spread (so one busy category can't dominate), article-age computation, and the
freshness disclosure that stops a stale cache being narrated as "the latest"
(added to close the "two-week-old news reported as breaking" bug). Runs in the
normal suite — no model, no network.
"""
from __future__ import annotations

import datetime as dt

import pytest

from eli.tools.news import news_synthesis as ns


# --------------------------------------------------------------------------- #
# _one_sentence_gist
# --------------------------------------------------------------------------- #
def test_gist_takes_first_sentence():
    assert ns._one_sentence_gist("First sentence. Second sentence.") == "First sentence."


def test_gist_multi_sentence():
    out = ns._one_sentence_gist("One. Two. Three.", max_sentences=2)
    assert out == "One. Two."


def test_gist_collapses_whitespace():
    assert ns._one_sentence_gist("hello   world\n\n  foo!") == "hello world foo!"


def test_gist_respects_cap():
    long = "word " * 200  # far over the cap
    assert len(ns._one_sentence_gist(long, cap=240)) <= 240


def test_gist_empty_is_empty():
    assert ns._one_sentence_gist("") == ""
    assert ns._one_sentence_gist(None) == ""


# --------------------------------------------------------------------------- #
# _spread_across_domains
# --------------------------------------------------------------------------- #
def _art(title, category):
    return {"title": title, "category": category, "source": category}


def test_spread_prefers_domain_diversity():
    arts = [
        _art("a1", "world"), _art("a2", "world"), _art("a3", "world"),
        _art("b1", "science"), _art("c1", "tech"),
    ]
    picked = ns._spread_across_domains(arts, 3)
    cats = {p["category"] for p in picked}
    # Round-robin: 3 picks should span all 3 domains, not 3 from "world".
    assert cats == {"world", "science", "tech"}


def test_spread_dedupes_by_title():
    arts = [_art("dup", "world"), _art("dup", "science"), _art("unique", "tech")]
    picked = ns._spread_across_domains(arts, 5)
    titles = [p["title"] for p in picked]
    assert titles.count("dup") == 1 and "unique" in titles


def test_spread_caps_at_n_and_available():
    arts = [_art("x", "world"), _art("y", "science")]
    assert len(ns._spread_across_domains(arts, 5)) == 2   # only 2 available
    assert len(ns._spread_across_domains(arts, 1)) == 1   # capped at n


# --------------------------------------------------------------------------- #
# _article_age_days
# --------------------------------------------------------------------------- #
def test_age_from_iso_published():
    today = dt.datetime.now().strftime("%Y-%m-%dT08:00:00Z")
    assert ns._article_age_days({"published": today}) == 0


def test_age_counts_days_back():
    ten_ago = (dt.datetime.now() - dt.timedelta(days=10)).strftime("%Y-%m-%dT08:00:00Z")
    assert ns._article_age_days({"published": ten_ago}) == 10


def test_age_from_rfc822_pubdate():
    # RSS <pubDate> style
    d = (dt.datetime.now() - dt.timedelta(days=3))
    rfc = d.strftime("%a, %d %b %Y %H:%M:%S +0000")
    age = ns._article_age_days({"published": rfc})
    assert age in (2, 3, 4)  # tolerant of tz/rounding


def test_age_falls_back_to_fetched_at():
    ts = (dt.datetime.now() - dt.timedelta(days=5)).timestamp()
    assert ns._article_age_days({"fetched_at": ts}) == 5


def test_age_none_when_no_usable_date():
    assert ns._article_age_days({}) is None
    assert ns._article_age_days({"published": "not a date"}) is None


# --------------------------------------------------------------------------- #
# Freshness disclosure — offline must never be narrated as "the latest"
# --------------------------------------------------------------------------- #
def test_offline_briefing_flags_stale_and_discloses(monkeypatch):
    import eli.core.config as cfg
    monkeypatch.setattr(cfg, "network_allowed", lambda: False)
    b = ns.build_news_briefing(refresh=False, top_n=3, interest_n=2)
    assert b.get("ok") is True
    assert b.get("offline") is True and b.get("stale") is True
    prompt = b.get("synthesis_prompt", "")
    assert "FRESHNESS" in prompt
    assert "MUST NOT imply any story is from today" in prompt


def test_online_fresh_cache_has_no_offline_flag(monkeypatch):
    import eli.core.config as cfg
    monkeypatch.setattr(cfg, "network_allowed", lambda: True)
    b = ns.build_news_briefing(refresh=False, top_n=3, interest_n=2)
    assert b.get("offline") is False
