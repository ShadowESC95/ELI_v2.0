"""Conversation must not be mistaken for a task.

Two live failures from one transcript:
  1. "Sound, thanks for clrifying Eli. I'm good…" made the file_code agent grep 7 files
     and inject 20 code snippets into a breakfast chat, because the CamelCase pattern
     treated the sentence-initial "Sound" as a code identifier.
  2. ELI said "still glitchy…"; the user asked "Why are you still glitchy?" and the LLM
     intent resolver fired SELF_ANALYZE, answering a personal question with a canned
     "Self-Analysis Report (0 recent issues)".
"""
from __future__ import annotations
import re
from eli.cognition.agent_bus import _filecode_extract_terms
from eli.cognition.scoring import term_overlap

CASUAL = [
    "Sound, thanks for clrifying Eli. I'm good, just after eating breakfast and watching rick an morty. you?",
    "What's up sahn?",
    "Nice one. How's your morning going?",
    "Good thanks. Just chilling.",
]
CODE = {
    "where is CognitiveEngine defined?": "cognitiveengine",
    "show me agent_bus.py": "agent_bus.py",
    "what does the AgentBus do?": "agentbus",
    "how does mic_resolver work?": "mic_resolver",
}


def test_casual_chat_yields_no_code_search_terms():
    for msg in CASUAL:
        assert _filecode_extract_terms(msg) == set(), f"{msg!r} triggered a repo search"


def test_real_code_questions_still_extract_terms():
    for msg, expected in CODE.items():
        assert expected in _filecode_extract_terms(msg), f"{msg!r} lost its search term"


def test_capitalised_english_is_not_an_identifier():
    # the exact regression: sentence-initial / proper nouns are not code symbols
    for word in ("Sound", "Thanks", "Morty", "Nice", "Good"):
        assert _filecode_extract_terms(f"{word} is a word.") == set()


def test_genuine_camelcase_still_matches():
    for ident in ("CognitiveEngine", "AgentBus", "ELIAudioSTT"):
        assert _filecode_extract_terms(f"look at {ident} please")


# ── follow-up-about-ELI's-own-reply must stay conversational ──
_EXPLICIT = (r"\b(analy[sz]e|diagnos|report|audit|log[s]?|status|metrics|"
             r"failures?|errors?|statistics|health\s*check)\b")
_LAST = "Sahns. Still glitchy, still running on the same old code. How's it going?"


def _would_redirect_to_chat(msg: str, last_reply: str) -> bool:
    if re.search(_EXPLICIT, msg, re.I):
        return False
    return len(msg.split()) <= 14 and term_overlap(msg, last_reply) >= 0.25


def test_followup_about_elis_own_words_becomes_chat():
    assert _would_redirect_to_chat("Why are you still glitchy?", _LAST)
    assert _would_redirect_to_chat("you just said that you were glitchy?", _LAST)


def test_explicit_self_report_requests_are_untouched():
    assert not _would_redirect_to_chat("analyse your failures", _LAST)
    assert not _would_redirect_to_chat("show me your self-improvement log", _LAST)
    assert not _would_redirect_to_chat("what's your runtime status", _LAST)


def test_unrelated_question_is_untouched():
    assert not _would_redirect_to_chat("what's the weather", _LAST)
