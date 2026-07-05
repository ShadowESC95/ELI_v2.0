"""
Regression tests for natural salience weighting + auto-capture.

ELI should weight statements by how memorable they are *from the content itself*
and promote genuinely important user statements into durable memory on its own —
without the user ever saying "remember this", and without chit-chat / questions
polluting the store. This is the general fix behind the "Shadow (my dog)" failure.
"""
import pathlib
import sqlite3
import tempfile

import pytest

from eli.memory.memory import Memory


@pytest.fixture
def mem(monkeypatch):
    # Force sparse durable results so recall exercises the real durable path
    # rather than being masked by the global FAISS store.
    import eli.memory.vector_store as vs
    monkeypatch.setattr(vs, "get_vector_store", lambda *a, **k: None)
    return Memory(db_path=pathlib.Path(tempfile.mktemp(suffix=".sqlite3")))


# ── Salience scoring is content-driven ──────────────────────────────────────

def test_facts_outscore_chitchat():
    fact = Memory._score_importance("i'm allergic to peanuts", None, "user", "fact")
    chat = Memory._score_importance("yeah that makes sense", None, "user", "memory")
    assert fact > chat
    assert fact >= 0.6
    assert chat <= 0.6


def test_questions_are_not_high_salience():
    q = Memory._score_importance("what is my dog's name?", None, "user", "fact")
    s = Memory._score_importance("my dog is called Shadow", None, "user", "fact")
    assert s > q, "a stated fact must outweigh a question"


@pytest.mark.parametrize("text,memorable", [
    ("my name is Jason", True),
    ("i'm allergic to peanuts", True),
    ("my daughter's birthday is on the 3rd of March", True),
    ("i just started a new job at a robotics lab", True),
    ("we adopted a rescue dog last week", True),
    ("my favourite band is Radiohead", True),
    ("Shadow (my dog) is very clever", True),
    # non-facts / queries / chit-chat:
    ("what is the weather today", False),
    ("what is my dog's name?", False),
    ("ok cool thanks", False),
    ("yeah", False),
    ("haha nice one", False),
])
def test_is_memorable_statement(text, memorable):
    assert Memory._is_memorable_statement(text) is memorable, text


# ── Auto-capture on the conversation-turn path ──────────────────────────────

def test_passing_fact_is_captured_and_recallable(mem):
    """A non-relational fact said in passing must become durable + recallable."""
    mem.add_conversation_turn("user", "by the way i'm allergic to peanuts")
    res = mem.recall_memory("what am i allergic to", limit=5)
    assert any("allergic to peanuts" in (r.get("text") or "") for r in res)


def test_chitchat_and_questions_not_promoted(mem):
    mem.add_conversation_turn("user", "ok cool thanks")
    mem.add_conversation_turn("user", "what is the weather like")
    conn = sqlite3.connect(mem.db_path)
    rows = [r[0] for r in conn.execute("SELECT text FROM memories").fetchall()]
    conn.close()
    assert rows == [], f"chit-chat/questions wrongly promoted: {rows}"


def test_assistant_turns_not_promoted(mem):
    mem.add_conversation_turn("assistant", "I think your dog Shadow sounds lovely.")
    conn = sqlite3.connect(mem.db_path)
    rows = [r[0] for r in conn.execute("SELECT text FROM memories").fetchall()]
    conn.close()
    assert rows == [], f"assistant turn wrongly promoted: {rows}"


def test_capture_is_deduplicated(mem):
    fact = "i'm allergic to peanuts and shellfish"
    for _ in range(3):
        mem.add_conversation_turn("user", fact)
    conn = sqlite3.connect(mem.db_path)
    n = conn.execute("SELECT COUNT(*) FROM memories WHERE text = ?", (fact,)).fetchone()[0]
    conn.close()
    assert n <= 1, f"same fact promoted {n} times"


def test_captured_fact_carries_content_salience(mem):
    mem.add_conversation_turn("user", "my daughter's birthday is on the 3rd of March")
    conn = sqlite3.connect(mem.db_path)
    imp = conn.execute(
        "SELECT importance FROM memories WHERE text LIKE '%birthday%'"
    ).fetchone()
    conn.close()
    assert imp is not None and imp[0] >= 0.7, "high-salience fact stored with low importance"
