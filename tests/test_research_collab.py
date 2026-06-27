"""Integration test: research collaboration (eli.runtime.research_corpus).

Shared corpora with attribution: contributors ingest files and add notes, every
contribution records who/when, documents() / members() / corpora() expose it, query
attribution feeds the activity log, and remove_document() supports collaborative edit
(rebuilding the FAISS index from the remaining vectors).

Runs in a clean subprocess with the REAL faiss + a deterministic fake embedder,
because the suite conftest mocks faiss/pydantic (it targets the cognition engine).
Everything is isolated to throwaway dirs + a throwaway audit DB — the real corpora
and ledger are never touched.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_DRIVER = textwrap.dedent(
    """
    import tempfile, os
    from pathlib import Path

    research_root = Path(tempfile.mkdtemp())     # corpus indexes
    source_root = Path(tempfile.mkdtemp())       # ingest sandbox
    audit_db = Path(tempfile.mkdtemp()) / "audit.sqlite3"

    import eli.runtime.research_corpus as RC
    import eli.runtime.evidence_ledger as L

    # Isolate storage (avoids get_paths() caching) + the audit ledger.
    RC._root = lambda: research_root
    RC.research_source_root = lambda: source_root
    L._default_db_path = lambda: audit_db

    # Deterministic fake embedder over a tiny vocab — no model needed.
    VOCAB = ["photon", "mass", "bread", "flour", "energy", "light", "note"]
    def _vec(t):
        t = t.lower()
        return [float(t.count(w)) for w in VOCAB] + [1.0]
    RC._embed_doc = lambda text: _vec(text)
    RC._embed_query = lambda text: _vec(text)

    # alice ingests a file
    (source_root / "photon.txt").write_text("The photon is a quantum of light. photon energy.")
    assert RC.ingest("proj", "photon.txt", user="alice")["ok"]
    # bob adds a note
    assert RC.add_note("proj", "Bread", "Bread is made from flour. note.", user="bob")["ok"]

    # documents carry attribution; members are the distinct contributors
    docs = {d["source"]: d for d in RC.documents("proj")}
    assert docs["photon.txt"]["added_by"] == "alice" and docs["photon.txt"]["kind"] == "file"
    assert docs["Bread"]["added_by"] == "bob" and docs["Bread"]["kind"] == "note"
    assert set(RC.members("proj")) == {"alice", "bob"}
    assert RC.corpora()[0]["members"] == 2

    # carol's query is attributed in the activity feed
    RC.query("proj", "tell me about the photon", user="carol")
    acts = {(a["action"], a["user"]) for a in RC.activity("proj")}
    assert {("INGEST", "alice"), ("NOTE", "bob"), ("QUERY", "carol")} <= acts

    # note edit: re-adding the same title replaces it (no duplicate)
    RC.add_note("proj", "Bread", "Bread updated. note note.", user="bob")
    assert sum(1 for d in RC.documents("proj") if d["source"] == "Bread") == 1

    # collaborative remove rebuilds the index from remaining vectors
    assert RC.remove_document("proj", "Bread", user="alice")["ok"]
    assert RC.members("proj") == ["alice"]
    assert [d["source"] for d in RC.documents("proj")] == ["photon.txt"]

    # the rebuilt index still answers (photon.txt survives)
    res = RC.query("proj", "photon", user="carol")
    assert res["ok"] and any(h["source"] == "photon.txt" for h in res["hits"])

    print("RESEARCH_COLLAB_OK")
    """
)


def test_research_collaboration_end_to_end():
    r = subprocess.run([sys.executable, "-c", _DRIVER],
                       cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode != 0 or "RESEARCH_COLLAB_OK" not in r.stdout:
        pytest.fail(f"research collaboration driver failed (rc={r.returncode})\n"
                    f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr[-2500:]}")
