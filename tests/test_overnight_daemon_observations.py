"""What the proactive daemon concluded while running unattended overnight.

From a live 2.2.5 session left on all night. The chat itself was healthy — the
reflection-telemetry fix held and a greeting no longer produced "I'm a patch
job" — but the background daemon reported three things that were not true.

1. THE USER'S FOCUS AREAS.

       [PROACTIVE] topic_focus: Current focus areas:
           afternoon (x11), doing (x10), today (x10), memory (x9), world (x7)

   The operator had said "afternoon, Eli". Four of those five words are in the
   reflection report's stopword set and would have been dropped — but the daemon
   carried a SECOND ~180-word list of its own that never received the fixes the
   first one did, and had no notion of small talk at all. reflection.py's own
   comment names the identical failure it had already fixed:

       "Filler that reached a live report as 'Top topics: doing, evening,
        afternoon, head, mean' — none of which was a subject anyone discussed."

   One canonical vocabulary now serves both, plus the phatic skip, so a greeting
   contributes no subjects rather than making "afternoon" the top interest.

2. WHAT WAS EMERGING.

       [PROACTIVE] trend_emerging: Emerging focus:
           doing, afternoon, talking, today, memory (not seen in prior ticks)

   The same five words, declared new, on every tick, all night. The writer
   stores {"patterns": [{"type": "topic_focus", "topics": [...]}]}, and the
   reader asked for a TOP-LEVEL "topics" key — so the set of past topics was
   always empty, everything looked new forever, and trend_fading (gated on that
   set being non-empty) could never fire at all.

3. WHAT IT HAD LEARNED ABOUT ITSELF.

       'Repeatedly starting the proactive daemon may indicate a need for more
        stable initialization or resource management.'

   Roughly twenty times overnight, in almost those words each time. The 30-minute
   throttle was working correctly; the input was the problem. Measured on that
   machine, agent.sqlite3 held 220 observations of which 104 were
   proactive_pattern_tick and 104 runtime, and the ten most recent rows in
   user.sqlite3 were "Proactive daemon started" repeated. The synthesiser asks
   the model to "reflect on your OWN recent activity" and handed it ten rows of
   its own bookkeeping, so it answered the question it was given. With nothing
   but plumbing to reflect on it now keeps the last real insight instead of
   spending an inference call restating its own start-up history.

4. A greeting the ROUTER already knew about. "afternoon, Eli" matches
   chat.greeting at 0.90, but the phatic detector held "good morning" and bare
   "night" while bare "morning"/"afternoon"/"evening" were absent, so the two
   disagreed about the same utterance.
"""
from __future__ import annotations

import json

import pytest

from eli.runtime.reflection import (
    TOPIC_STOPWORDS, contributes_topics, topic_words,
)


# ── 1. the words reported as the operator's interests ──────────────────────
@pytest.mark.parametrize("word", ["afternoon", "doing", "today", "talking", "evening", "morning"])
def test_the_reported_focus_areas_are_filler(word):
    assert word in TOPIC_STOPWORDS


def test_a_greeting_contributes_no_topics():
    """"afternoon, Eli" is a hello, not an interest in afternoons."""
    assert topic_words("afternoon, Eli") == set()
    assert topic_words("morning, Eli") == set()
    assert not contributes_topics("afternoon, Eli")


def test_a_real_message_still_yields_its_subjects():
    got = topic_words("the router keeps dropping wexford weather requests")
    assert {"router", "wexford", "weather"} <= got
    assert "doing" not in got


def test_the_daemon_uses_the_shared_vocabulary():
    """Not a second list that drifts. This is the whole point of the fix."""
    import inspect

    from eli.planning import proactive_daemon

    src = inspect.getsource(proactive_daemon)
    i = src.index("Pattern 2: Meaningful topic focus")
    window = src[i:i + 2000]
    assert "from eli.runtime.reflection import topic_words" in window


# ── 2. trend detection must read the shape it writes ───────────────────────
def test_the_stored_pattern_shape_is_the_shape_that_is_read():
    """The writer nests topics inside patterns[]; a top-level lookup found
    nothing, so every topic was 'not seen in prior ticks' forever."""
    payload = json.dumps({
        "patterns": [
            {"type": "time_habit", "topics": []},
            {"type": "topic_focus", "topics": ["wexford", "router"]},
        ],
        "ts": 0,
    })
    data = json.loads(payload)

    # The old reader.
    assert data.get("topics", []) == [], "premise: a top-level key finds nothing"

    # The new reader.
    past = set()
    for p in data.get("patterns", []) or []:
        if str((p or {}).get("type") or "") == "topic_focus":
            for t in (p or {}).get("topics", []) or []:
                past.add(str(t).lower())
    assert past == {"wexford", "router"}


def test_the_daemon_reads_topics_out_of_patterns():
    import inspect

    from eli.planning import proactive_daemon

    src = inspect.getsource(proactive_daemon)
    i = src.index("Trend detection: compare against last stored observation")
    window = src[i:i + 2200]
    code = "\n".join(l for l in window.splitlines() if not l.lstrip().startswith("#"))
    assert '_obs_data.get("patterns"' in code, \
        "trend detection still reads a top-level topics key that is never present"


def test_a_repeat_tick_reports_nothing_as_emerging():
    """Identical topics two ticks running are not a new trend."""
    cur = {"wexford", "router"}
    past = {"wexford", "router"}
    assert not (cur - past)


# ── 3. the synthesiser must not reflect on its own plumbing ────────────────
PLUMBING = [
    {"category": "proactive_pattern_tick", "observation": '{"patterns": [], "ts": 1}'},
    {"category": "runtime", "observation": "pattern_summary"},
    {"category": "system", "observation": "Proactive daemon started"},
    {"category": "world_autonomy", "observation": "[world_suggestion] SELF_IMPROVE"},
    {"category": "awareness", "observation": "Persona auto-overlay cleaned: noise pruned."},
]


@pytest.mark.parametrize("row", PLUMBING)
def test_plumbing_observations_are_not_reflection_material(row):
    from eli.planning.insight_synthesis import _observation_text

    assert _observation_text(row) == ""


def test_a_genuine_observation_survives():
    from eli.planning.insight_synthesis import _observation_text

    row = {"category": "habit_detector",
           "observation": "User analysed three PDFs in the QMSH project this evening"}
    assert "QMSH" in _observation_text(row)


def test_no_inference_is_spent_when_only_plumbing_remains(monkeypatch, tmp_path):
    """The overnight behaviour: a call every 30 minutes to restate its own
    start-up history. With nothing real to say it must keep the cached insight
    and not reach the model at all."""
    from eli.planning import insight_synthesis as ins

    monkeypatch.setattr(ins, "_cache_path", lambda: tmp_path / "insight.json")
    (tmp_path / "insight.json").write_text(
        json.dumps({"insight": "previous real insight", "ts": 0}), encoding="utf-8")

    class _Mem:
        def get_recent_observations(self, limit=20):
            return list(PLUMBING)

        def get_session_summaries(self, *a, **k):
            return []

    called = []

    class _Broker:
        gguf_ready = True

        def infer(self, *a, **k):
            called.append(1)
            return "should never be reached"

    monkeypatch.setattr("eli.cognition.inference_broker.get_inference_broker",
                        lambda: _Broker())
    monkeypatch.setattr("eli.cognition.inference_broker.foreground_recently_active",
                        lambda: False)
    import eli.cognition.gguf_inference as _gi
    monkeypatch.setattr(_gi, "is_loaded", lambda: True, raising=False)

    out = ins.refresh_insight(memory=_Mem(), force=True)
    assert not called, "spent an inference call on nothing but daemon bookkeeping"
    assert out == "previous real insight"


# ── 4. the detector and the router must agree about a greeting ─────────────
@pytest.mark.parametrize("greeting", [
    "afternoon, Eli", "afternoon", "morning", "morning, Eli",
    "evening", "evening Eli", "good evening", "good day",
])
def test_bare_time_of_day_greetings_are_phatic(greeting):
    from eli.kernel.engine import _is_brief_phatic_prompt as phatic

    assert phatic(greeting)


def test_the_router_agreed_all_along():
    """It classified this exact utterance as chat.greeting at 0.90."""
    from eli.execution.router_enhanced import route

    assert route("afternoon, Eli").get("action") == "CHAT"


def test_a_substantive_afternoon_sentence_is_not_phatic():
    from eli.kernel.engine import _is_brief_phatic_prompt as phatic

    assert not phatic("what is the weather this afternoon in Wexford")
    assert not phatic("the sun is not that cheerful and it is only afternoon for 30 minutes")
