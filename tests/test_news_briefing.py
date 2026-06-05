"""Deterministic core of the conversational news briefing (no model needed)."""
from eli.tools.news.news_synthesis import _one_sentence_gist, _spread_across_domains


def test_one_sentence_gist_takes_first_sentence():
    summary = "Scientists found a new exoplanet. It orbits a red dwarf. More study is planned."
    assert _one_sentence_gist(summary) == "Scientists found a new exoplanet."


def test_one_sentence_gist_empty_and_whitespace():
    assert _one_sentence_gist("") == ""
    assert _one_sentence_gist("   \n  ") == ""
    assert _one_sentence_gist(None) == ""


def test_one_sentence_gist_caps_length():
    long = "word " * 200
    assert len(_one_sentence_gist(long)) <= 240


def _mk(title, category, source="Src"):
    return {"title": title, "category": category, "source": source, "summary": ""}


def test_spread_prefers_domain_diversity():
    # Four tech, two science, one world — spreading should not return all tech.
    articles = [
        _mk("t1", "tech"), _mk("t2", "tech"), _mk("t3", "tech"), _mk("t4", "tech"),
        _mk("s1", "science"), _mk("s2", "science"),
        _mk("w1", "world"),
    ]
    picked = _spread_across_domains(articles, 3)
    cats = [a["category"] for a in picked]
    assert len(picked) == 3
    # Round-robin: first pick from each distinct domain before a second from any.
    assert set(cats) == {"tech", "science", "world"}


def test_spread_dedupes_titles_and_respects_n():
    articles = [
        _mk("dup", "tech"), _mk("dup", "science"),  # same title, different domain
        _mk("a", "world"), _mk("b", "health"),
    ]
    picked = _spread_across_domains(articles, 10)
    titles = [a["title"] for a in picked]
    assert titles.count("dup") == 1          # deduped
    assert len(picked) == 3                  # dup + a + b


def test_spread_handles_empty():
    assert _spread_across_domains([], 5) == []
