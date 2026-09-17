"""ELI's own reflection telemetry must not come back as memories about itself.

From a live 2.2.4 session. The user opened with "What's up, bud?" and got:

    "Chilling in the Reflection Chamber, trying to make sense of why I keep
     talking about glitches like they're part of my daily routine."

and it escalated from there — "I'm a patch job", "a walking glitch", "I'm
broken", "I'm not sure if I'm supposed to be talking to you" — until the user
said "you are insane".

None of that came from the persona: the words "glitch", "patch job" and "broken"
appear nowhere in persona.txt. They came from ELI's own memory. Measured on that
machine, of the memories that passed the recall noise filter:

    257 recallable  ->  242 were ELI's own reflection telemetry  (94%)
     15 were real user memories

and the single highest-ranked row ELI could recall about itself was

    "Recent issues: 4 failure-related memories stored"   importance 1.0

next to a keyword tally reading "Top topics: stop, glitchy, breakfast, rick,
morty". The model was reciting its own bookkeeping as autobiography — "glitchy"
was a word the USER had typed about a bug, counted into a statistic, stored as a
memory, and read back as a property of ELI.

Three defects, all of them mechanical:

  * reflection stored each insight under kind='insight' / tags=['eli_insight',
    'auto'] / source='eli_reflection' — a combination chosen in a comment
    BECAUSE it dodges every clause of the recall noise filter;
  * the duplicate check asked recall_memory(..., limit=5) whether the new text
    was among five relevance-ranked rows, which is not an existence check, so
    the same reflection was appended over and over (135 rows, 34 exact dupes,
    six identical copies of one);
  * the engine stored the insights a SECOND time, with no duplicate check at
    all, on top of the copy reflect_on_period had already written.

Nothing legitimate is hidden by the fix: every one of the 242 rows was one of
seven statistic families (Conversation volume, Top topics, User correction
signals, Recent issues, User model focus, Repeated actions, App usage), and the
"what patterns have you noticed" path is served by ReflectionAgent, which reads
the observations and session_summaries tables rather than this one.
"""
from __future__ import annotations

import sqlite3
import uuid

import pytest

from eli.memory import get_memory


TELEMETRY = [
    "Conversation volume: 21 user messages in last 24h",
    "Top topics: stop, glitchy, breakfast, rick, morty",
    "Recent issues: 4 failure-related memories stored",
    "User correction/challenge signals: 1 recent events",
    "Repeated actions: ANALYZE_PDF on report.pdf (3x)",
    "App usage: firefox (5x)",
]


@pytest.fixture()
def mem():
    return get_memory()


@pytest.fixture()
def unique():
    """The _pytest store persists between runs, so a test that asserts a row is
    ABSENT before storing it must use text no earlier run can have written."""
    return uuid.uuid4().hex[:12]


# ── the telemetry must not surface as a memory ─────────────────────────────
@pytest.mark.parametrize("text", TELEMETRY)
def test_reflection_telemetry_does_not_surface_in_recall(mem, text):
    mem.store_memory(
        text, tags=["eli_insight", "auto"], kind="insight",
        source="eli_reflection", importance=1.0,
    )
    # Query with the row's own words — the strongest possible retrieval cue.
    hits = mem.recall_memory(text, limit=25) or []
    surfaced = [h for h in hits if text[:30].lower() in str(h.get("text", "")).lower()]
    assert not surfaced, f"reflection telemetry reached recall: {surfaced[:1]}"


def test_a_real_user_memory_still_surfaces(mem):
    """The filter must cut telemetry, not memory itself."""
    fact = "my dog is called Biscuit and he is a beagle"
    mem.store_memory(fact, tags=["user_fact"])
    hits = mem.recall_memory("dog called Biscuit", limit=25) or []
    assert any("biscuit" in str(h.get("text", "")).lower() for h in hits), \
        "a genuine user fact stopped being recallable"


def test_the_source_is_what_is_filtered(mem):
    """Same text, ordinary source — still recallable. It is provenance that
    disqualifies it, not the words."""
    text = "Top topics: quantum coherence, entropy fields"
    mem.store_memory(text, tags=["user_fact"], source="user")
    hits = mem.recall_memory("quantum coherence entropy", limit=25) or []
    assert any("quantum coherence" in str(h.get("text", "")).lower() for h in hits)


def test_noise_sources_names_the_reflection_writer():
    """The vocabulary now lives at the choke point (eli/core/self_provenance),
    not inline in the recall query — this asserts the invariant rather than the
    shape of the code that enforces it."""
    from eli.core.self_provenance import MEMORY_SOURCES, memory_exclusion_sql

    assert "eli_reflection" in MEMORY_SOURCES
    _, params = memory_exclusion_sql({"kind", "source", "tags"}, alias="")
    assert "eli_reflection" in params


# ── duplicate suppression must be an existence check ───────────────────────
def test_already_stored_detects_an_exact_duplicate(mem, unique):
    from eli.runtime.reflection import _already_stored

    text = f"Reflection (24h): Conversation volume: 99 messages [{unique}]"
    assert not _already_stored(mem, text)
    mem.store_memory(text, tags=["reflection", "auto"])
    assert _already_stored(mem, text), \
        "an identical reflection was not recognised as already stored"


def test_already_stored_does_not_false_positive(mem, unique):
    from eli.runtime.reflection import _already_stored

    assert not _already_stored(mem, f"Reflection (24h): never reflected on [{unique}]")


def test_a_near_miss_is_not_treated_as_a_duplicate(mem, unique):
    """Different counts are different reflections and both must be storable."""
    from eli.runtime.reflection import _already_stored

    a = f"Reflection (24h): Conversation volume: 11 messages [{unique}]"
    b = f"Reflection (24h): Conversation volume: 12 messages [{unique}]"
    mem.store_memory(a, tags=["reflection", "auto"])
    assert _already_stored(mem, a)
    assert not _already_stored(mem, b)


def test_repeated_reflection_does_not_multiply_rows(mem, unique):
    """The live failure: the same reflection appended once per cycle."""
    from eli.runtime import reflection

    def _count(con, text):
        return con.execute(
            "SELECT COUNT(*) FROM memories WHERE text = ?", (text,)
        ).fetchone()[0]

    text = f"Reflection (24h): Conversation volume: 7 messages [{unique}]"
    for _ in range(5):
        if not reflection._already_stored(mem, text):
            mem.store_memory(text, tags=["reflection", "auto"])

    con = sqlite3.connect(f"file:{mem.db_path}?mode=ro", uri=True)
    try:
        assert _count(con, text) == 1
    finally:
        con.close()


# ── the engine must not write the same insights a second time ──────────────
def test_the_engine_does_not_double_store_reflection_insights():
    """reflect_on_period already persists them; the engine storing them again
    was the unbounded-growth half of the bug."""
    import inspect

    from eli.kernel import engine

    src = inspect.getsource(engine)
    i = src.index("eli-reflection:")
    window = src[i:i + 1200]
    code = "\n".join(l for l in window.splitlines() if not l.lstrip().startswith("#"))
    assert "store_memory" not in code, \
        "the engine is storing reflection insights again on top of reflect_on_period"


# ── "nothing happened" vs "couldn't check" ──────────────────────────────────
#
# Every data source reflect_on_period reads is independently try/excepted, so
# one bad source doesn't kill the whole reflection. That used to mean a
# section that genuinely found nothing and a section that flat-out FAILED
# produced the identical confident conclusion: "No evidence-backed activity
# signals recorded for this period." A periodic self-report that can't tell
# those apart is exactly the "confidently lying about its own certainty"
# failure class for a product whose pitch is trustworthy local intelligence.
class _ReflectionMemBase:
    def store_memory(self, *a, **kwargs):
        return {"ok": True, "id": 1}

    db_path = None  # _already_stored() degrades to "not stored" cleanly on this


class _AllSectionsFailMem(_ReflectionMemBase):
    """Every method reflect_on_period calls on `mem` raises."""
    def get_habit_events(self, **kwargs):
        raise RuntimeError("habit db locked")

    def get_recent_conversation(self, **kwargs):
        raise RuntimeError("conversation db locked")

    def recall_memory(self, *a, **kwargs):
        raise RuntimeError("memory db locked")


class _AllSectionsCleanEmptyMem(_ReflectionMemBase):
    """Every method succeeds and honestly reports nothing found."""
    def get_habit_events(self, **kwargs):
        return []

    def get_recent_conversation(self, **kwargs):
        return []

    def recall_memory(self, *a, **kwargs):
        return []


@pytest.fixture()
def _isolated_evidence_and_user_model(monkeypatch):
    """The evidence-ledger and user-model sections read real on-disk state via
    their own separately-imported functions, not through `mem` -- isolate them
    too so these tests are deterministic regardless of what this machine has
    actually logged."""
    import eli.runtime.evidence_ledger as ledger
    import eli.runtime.user_model as user_model

    monkeypatch.setattr(ledger, "repeated_event_signals", lambda **kw: [])
    monkeypatch.setattr(ledger, "recent_events", lambda **kw: [])
    monkeypatch.setattr(ledger, "recent_generated_artifacts", lambda **kw: [])
    monkeypatch.setattr(user_model, "read_user_model", lambda: {"is_seeded": False})


def test_all_sections_failing_is_not_reported_as_nothing_happened(
    monkeypatch, _isolated_evidence_and_user_model,
):
    from eli.runtime import reflection

    monkeypatch.setattr(reflection, "get_memory", lambda: _AllSectionsFailMem())
    out = reflection.reflect_on_period(hours=24)

    assert out["section_errors"], "failures must be recorded, not silently absorbed"
    joined = " ".join(out["insights"])
    assert "No evidence-backed activity signals recorded" not in joined, (
        "a reflection where every data source errored must not claim a "
        "verified 'nothing happened'"
    )
    assert "not a confirmed" in joined.lower() or "could not fully verify" in joined.lower()


def test_all_sections_genuinely_empty_still_says_so_honestly(
    monkeypatch, _isolated_evidence_and_user_model,
):
    """The original honest message must survive for the case it was actually
    right for: everything was checked, and there was truly nothing to report."""
    from eli.runtime import reflection

    monkeypatch.setattr(reflection, "get_memory", lambda: _AllSectionsCleanEmptyMem())
    out = reflection.reflect_on_period(hours=24)

    assert out["section_errors"] == []
    assert any("No evidence-backed activity signals recorded" in i for i in out["insights"])
