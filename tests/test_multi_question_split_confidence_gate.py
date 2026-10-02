"""Live session report (2026-10-02): "Well we just need to get head on quantum
dynamic encryption, send that note to MI5 will you? What is the news headline
about cosmic dust and venus's atmosphere?" split into two sub-questions
(engine.py's multi-question splitter). The first segment is a sarcastic aside,
not a real question, but it still passed the word-count gate, got routed
independently, and landed on a low-confidence identity/memory-dump fallback —
which then got silently concatenated in front of the real news answer.

Fix: each segment's result dict is checked for `confidence`; anything below
0.5 is dropped instead of joined into the final response.
"""
from eli.kernel.engine import CognitiveEngine

COMPOUND = (
    "Well we just need to get head on quantum dynamic encryption, send that "
    "note to MI5 will you? What is the news headline about cosmic dust and "
    "venus's atmosphere?"
)


def _engine_with_scripted_segments(responses):
    """Real engine, real splitter logic for the top-level call; recursive
    self.process() calls for each sub-question return the scripted dicts."""
    eng = CognitiveEngine()
    real_process = eng.process
    state = {"n": 0}

    def fake_process(user_input, *a, **kw):
        state["n"] += 1
        if state["n"] == 1:
            return real_process(user_input, *a, **kw)
        return responses[state["n"] - 2]

    eng.process = fake_process
    return eng


def test_low_confidence_segment_is_dropped_not_concatenated():
    eng = _engine_with_scripted_segments([
        {"response": "Personal memory summary from active local DB: ...",
         "confidence": 0.2},
        {"response": "Cosmic dust is the source of Venus's atmospheric haze.",
         "confidence": 0.95},
    ])
    out = eng.process(COMPOUND, stream=False)
    assert "Personal memory summary" not in out
    assert "Cosmic dust" in out


def test_both_high_confidence_segments_are_both_kept():
    eng = _engine_with_scripted_segments([
        {"response": "Quantum encryption note not something I can send to MI5.",
         "confidence": 0.9},
        {"response": "Cosmic dust is the source of Venus's atmospheric haze.",
         "confidence": 0.95},
    ])
    out = eng.process(COMPOUND, stream=False)
    assert "Quantum encryption" in out
    assert "Cosmic dust" in out


def test_missing_confidence_is_not_treated_as_low():
    """Not every handler reports confidence — absence must not suppress a
    legitimate answer."""
    eng = _engine_with_scripted_segments([
        {"response": "No confidence field here."},
        {"response": "Cosmic dust is the source of Venus's atmospheric haze.",
         "confidence": 0.95},
    ])
    out = eng.process(COMPOUND, stream=False)
    assert "No confidence field here" in out
    assert "Cosmic dust" in out


def test_both_low_confidence_falls_through_to_normal_single_pass():
    """If every segment gets dropped, the splitter must not return an empty
    string — it falls through to the normal, single-query path below it."""
    eng = _engine_with_scripted_segments([
        {"response": "garbage", "confidence": 0.1},
        {"response": "also garbage", "confidence": 0.2},
    ])
    out = eng.process(COMPOUND, stream=False)
    # Falls through past the splitter entirely; whatever the normal pipeline
    # does next, it must not be the raw garbled sub-answers joined together.
    assert out != "garbage\n\nalso garbage"
