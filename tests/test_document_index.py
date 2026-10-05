"""The document index: what ELI reads is kept whole and found again by passage.

Before it, `engine.document_rag` was never set (the orchestrator logged "rag: 0" on every turn),
and the reader hands a reply the first 8000 characters of the first 20 pages, so anything further
into a document did not exist for ELI.
"""
from __future__ import annotations

import sqlite3
import sys
import types
import zlib
from types import SimpleNamespace

import numpy as np
import pytest

from eli.memory import document_index as di

FILLER = "The committee met again and discussed the usual matters at length without reaching a decision. " * 200
FACT = "The third high-risk category is biometric identification in public spaces."


def _fake_embed(text):
    """Words hashed into a vector: shared words mean a high cosine. Enough to rank passages."""
    v = np.zeros(96, dtype="float32")
    for t in di._terms(str(text).replace("search_document: ", "")):
        v[zlib.crc32(t.encode()) % 96] += 1.0
    return v


@pytest.fixture()
def index(tmp_path):
    return di.DocumentIndex(tmp_path / "documents.sqlite3", embed=_fake_embed)


@pytest.fixture()
def pack(tmp_path):
    p = tmp_path / "harbour_pack.md"
    p.write_text("# Harbour coursework pack\n\n" + FILLER + "\n\n" + FACT + "\n\n" + FILLER)
    return p


@pytest.fixture()
def live_index(tmp_path, monkeypatch):
    """The install's own index, as the engine and the executor reach it."""
    monkeypatch.setenv("ELI_DOCUMENT_INDEX", "1")
    monkeypatch.setenv("ELI_DOCUMENT_INDEX_DB", str(tmp_path / "live.sqlite3"))
    ix = di.get_document_index()
    ix._embed_fn = _fake_embed
    ix._refreshed = True  # no walk over the checkout's own notes
    yield ix
    ix.wait(10)
    di._indexes.pop(str(tmp_path / "live.sqlite3"), None)


def test_a_fact_far_past_the_readers_preview_is_found(index, pack):
    from eli.plugins.document_reader.plugin import DocumentReaderPlugin
    assert FACT not in DocumentReaderPlugin().read({"path": str(pack)})["content"]  # the reply never saw it
    added = index.add(pack, source="READ_FILE")
    assert added["ok"] and added["passages"] > 20
    hits = index.search("what is the third high-risk category in the harbour pack?", 3)
    assert any(FACT in h["text"] for h in hits)
    assert hits[0]["title"] == "harbour_pack.md" and hits[0]["parts"] == added["passages"]


def test_every_page_of_a_pdf_is_stored_with_its_page_number(index, tmp_path, monkeypatch):
    pages = [f"Page {i} is about nothing in particular and says so at some length." for i in range(1, 61)]
    pages[39] = "The reactor's coolant must be replaced every eighteen months, per section 4.2."

    class _Reader:
        def __init__(self, path):
            self.pages = [SimpleNamespace(extract_text=lambda t=t: t) for t in pages]

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=_Reader))
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.4 stand-in")
    from eli.plugins.document_reader.plugin import DocumentReaderPlugin, document_sections
    assert "coolant" not in DocumentReaderPlugin().read({"path": str(pdf)})["content"]  # page 40 is past the preview
    assert len(document_sections(pdf)) == 60
    index.add(pdf)
    hit = index.search("how often must the reactor coolant be replaced?", 2)[0]
    assert "eighteen months" in hit["text"] and hit["where"] == "p. 40"
    assert "[manual.pdf | p. 40, part" in di.format_passages([{"meta": hit}])


def test_passages_overlap_and_start_on_a_word():
    parts = di.passages([("", "alpha beta gamma delta epsilon. " * 200)])
    assert len(parts) > 5
    assert all(text.split()[0] in {"alpha", "beta", "gamma", "delta", "epsilon."} for _, text in parts)
    assert parts[0][1][-40:] in parts[0][1] and parts[1][1][:20] in parts[0][1]  # the second starts inside the first


def test_an_unchanged_document_is_not_stored_twice_and_a_changed_one_is_replaced(index, pack):
    first = index.add(pack)
    again = index.add(pack)
    assert again.get("unchanged") and again["doc_id"] == first["doc_id"] and index.stats()["documents"] == 1
    pack.write_text("Entirely new content about lighthouse keepers and their logbooks.")
    index.add(pack)
    assert index.stats() == {"documents": 1, "passages": 1, "embedded": 1}
    assert index.search("lighthouse keepers", 2) and not index.search("biometric identification", 2)


@pytest.mark.parametrize("name", [".env", "id_rsa.txt", "passwords.txt", "api_token.md", "wallet-recovery-codes.txt",
                                  "photo.png", "data.sqlite3", "script.py"])
def test_secrets_and_non_documents_are_never_stored(index, tmp_path, name):
    p = tmp_path / name
    p.write_text("AWS_SECRET=abc123 and other things nobody should index")
    assert not di.indexable(p)
    assert not index.add(p)["ok"] and not index.note(p) and index.stats()["documents"] == 0


def test_one_users_documents_are_not_shown_to_another(index, pack, monkeypatch):
    monkeypatch.setattr("eli.kernel.state.get_active_user_id", lambda *a, **k: "owner")
    index.add(pack, user_id="owner")
    assert index.search("biometric identification", 3, user_id="owner")
    assert index.search("biometric identification", 3, user_id="guest") == []
    assert index.documents("guest") == [] and not index.mentions("the harbour pack", "guest")
    assert index.remove([1], user_id="guest") == [] and index.stats()["documents"] == 1


def test_a_question_that_is_not_about_a_document_gets_only_passages_that_bear_on_it(index, tmp_path):
    garden = tmp_path / "plot.txt"
    garden.write_text("Tomatoes need six hours of sun a day. Water the basil every second day in summer.")
    index.add(garden)
    assert index.search("who won the world cup in 2022?", 3, strict=True) == []
    assert index.search("what is the weather like tomorrow", 3, strict=True) == []
    assert index.search("do tomatoes need six hours of sun a day?", 3, strict=True)


def test_a_question_naming_a_document_stays_inside_it(index, pack, tmp_path):
    other = tmp_path / "minutes.txt"
    other.write_text("The committee met again and discussed biometric turnstiles for the car park.")
    index.add(pack)
    index.add(other)
    assert index.mentions("what does the harbour pack say about categories")
    hits = index.search("what does the harbour pack say about biometric identification", 5)
    assert hits and {h["title"] for h in hits} == {"harbour_pack.md"}


def test_that_file_means_the_one_read_last(index, pack, tmp_path):
    index.add(pack)
    later = tmp_path / "plot.txt"
    later.write_text("Slugs go for the lettuce first; copper tape around the bed keeps most of them off.")
    index.add(later)
    hits = index.search("what did that file say about pests", 3)
    assert hits and hits[0]["title"] == "plot.txt"


def test_removing_a_document_removes_everything_made_from_it(index, pack):
    doc_id = index.add(pack)["doc_id"]
    gone = index.remove([doc_id])
    assert [d["title"] for d in gone] == ["harbour_pack.md"] and pack.exists()
    assert index.stats() == {"documents": 0, "passages": 0, "embedded": 0}
    con = sqlite3.connect(index._db)
    assert con.execute("SELECT COUNT(*) FROM passages_fts WHERE passages_fts MATCH 'biometric'").fetchone()[0] == 0
    con.close()
    assert index.search("biometric identification", 3) == []


def test_indexing_and_removing_are_written_to_the_evidence_ledger(index, pack, monkeypatch):
    events = []
    monkeypatch.setattr("eli.runtime.evidence_ledger.record_event", lambda *a, **k: events.append((a, k)) or 1)
    index.add(pack, user_id="", source="READ_FILE")
    index.remove([1])
    assert [(a[0], k["action"]) for a, k in events] == [("document_index", "INDEX"), ("document_index", "REMOVE")]
    assert events[0][1]["subject"] == str(pack) and "via READ_FILE" in events[0][1]["content"]


def test_wording_still_finds_passages_without_an_embedder_or_fts5(tmp_path, pack):
    ix = di.DocumentIndex(tmp_path / "plain.sqlite3", embed=lambda text: None)
    ix._fts = False
    ix.add(pack)
    assert ix.stats()["embedded"] == 0
    assert any(FACT in h["text"] for h in ix.search("third high-risk category biometric", 3))


def test_a_document_an_action_reads_is_indexed_behind_the_reply(live_index, pack):
    from eli.execution.executor_enhanced import _action_post_dispatch
    _action_post_dispatch("READ_FILE", {"path": str(pack)}, {"ok": True, "action": "READ_FILE", "path": str(pack), "content": "x"})
    _action_post_dispatch("OPEN_APP", {"path": str(pack)}, {"ok": True})
    _action_post_dispatch("READ_FILE", {"path": str(pack) + ".missing"}, {"ok": False})
    assert live_index.wait(20)
    docs = live_index.documents()
    assert [d["title"] for d in docs] == ["harbour_pack.md"] and docs[0]["source"] == "READ_FILE"


def test_the_index_can_be_switched_off(monkeypatch, pack):
    monkeypatch.setenv("ELI_DOCUMENT_INDEX", "0")
    assert di.get_document_index() is None and di.note_document(pack) is False


def _orchestrator(index):
    from eli.cognition.orchestrator import LongTermMemoryRefs, OrchestratorMemoryAgent, PlannerAgent
    engine = SimpleNamespace(document_rag=index, user_id="", memory=SimpleNamespace())
    return engine, PlannerAgent(engine), OrchestratorMemoryAgent(engine), LongTermMemoryRefs


def test_the_orchestrator_reads_documents_when_asked_about_one_in_any_mode(index, pack):
    index.add(pack)
    _, planner, agent, _ = _orchestrator(index)
    asked = "what does the harbour pack say the third high-risk category is?"
    for mode in ("quick", "chain_of_thought", "research"):
        plan = planner.plan_retrieval(asked, {"action": "CHAT"}, "", None, reasoning_mode=mode)
        assert plan["need_rag"] and not plan["rag_strict"] and plan["rag_limit"] >= 2, mode
    hits = agent.document_rag_search(asked, 4)
    assert hits and hits[0]["source"] == "rag" and any(FACT in h["text"] for h in hits)
    block = di.format_passages(hits, max_chars=4000)
    assert block.startswith("Passages from documents you have read") and "[harbour_pack.md | part" in block and FACT in block


def test_other_questions_do_not_pull_documents_into_a_quick_prompt(index, pack):
    index.add(pack)
    _, planner, _, _ = _orchestrator(index)
    quick = planner.plan_retrieval("how are you today?", {"action": "CHAT"}, "", None, reasoning_mode="quick")
    assert not quick["need_rag"] and quick["rag_limit"] == 0
    normal = planner.plan_retrieval("how are you today?", {"action": "CHAT"}, "", None, reasoning_mode="chain_of_thought")
    assert normal["need_rag"] and normal["rag_strict"]


def test_with_nothing_indexed_no_mode_searches_documents(index):
    _, planner, _, _ = _orchestrator(index)
    for mode in ("quick", "chain_of_thought"):
        assert not planner.plan_retrieval("what does the pdf say?", {"action": "CHAT"}, "", None, reasoning_mode=mode)["need_rag"]


def test_a_file_handed_over_with_the_message_is_read_on_that_turn(index, pack, tmp_path):
    other = tmp_path / "minutes.txt"
    other.write_text("Minutes of the allotment society. Biometric turnstiles were discussed for the car park.")
    index.add(other)
    _, planner, agent, _ = _orchestrator(index)
    message = f"what is this about?\n\n[File: {pack}]"
    plan = planner.plan_retrieval(message, {"action": "CHAT"}, "", None, reasoning_mode="quick")
    assert plan["need_rag"] and not plan["rag_strict"]
    hits = agent.document_rag_search(message, 3)
    assert index.wait(20)
    assert hits and {h["meta"]["title"] for h in hits} == {"harbour_pack.md"}
    assert hits[0]["meta"]["part"] == 1  # too general a question to match a passage: how the document opens


def test_document_passages_outrank_ordinary_evidence_when_the_prompt_is_trimmed():
    from eli.cognition.context_budget import _rank
    assert _rank("Passages from documents you have read (the documents' own words") < _rank("Reranked evidence:")


def test_the_engine_exposes_the_index_to_the_orchestrator(live_index):
    from eli.kernel.engine import CognitiveEngine
    assert CognitiveEngine.document_rag.fget(SimpleNamespace()) is live_index


def test_forgetting_a_document_asks_first_and_leaves_the_file(live_index, pack, monkeypatch):
    from eli.execution import executor_enhanced as ex
    from eli.execution.router_enhanced import route
    live_index.add(pack)
    monkeypatch.setattr("eli.memory.memory.Memory.forget_candidates", lambda self, q, limit=8: [])
    asked = ex.execute("MEMORY_FORGET", {"query": "the harbour pack"})
    assert asked["ok"] and "document #1: harbour_pack.md" in asked["content"] and live_index.stats()["documents"] == 1
    confirm = route("confirm forget documents 1")
    assert confirm["action"] == "MEMORY_FORGET" and confirm["args"] == {"document_ids": [1], "confirm": True}
    done = ex.execute("MEMORY_FORGET", confirm["args"])
    assert done["ok"] and "Removed from the document index: harbour_pack.md" in done["content"]
    assert live_index.stats()["documents"] == 0 and pack.exists()


def test_the_first_reach_for_the_index_picks_up_elis_own_folders(index, tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "amplituhedron.md").write_text("The amplituhedron is a geometric object whose volume gives scattering amplitudes.")
    (notes / "settings.json").write_text("{}")
    index.refresh_once([notes])
    index.refresh_once([notes])  # once is once
    for _ in range(100):
        if index.stats()["documents"]:
            break
        __import__("time").sleep(0.05)
    assert index.wait(20)
    assert [d["title"] for d in index.documents()] == ["amplituhedron.md"]


def test_a_document_edited_on_disk_is_read_again(index, pack):
    import os
    index.add(pack)
    pack.write_text("Rewritten: the pack now covers lighthouse keepers only.")
    os.utime(pack, (pack.stat().st_atime, pack.stat().st_mtime + 60))
    assert index.refresh() == 1 and index.wait(20)
    assert index.search("lighthouse keepers", 2) and not index.search("biometric identification", 2)


def test_the_self_model_counts_what_has_been_read(live_index, pack):
    from eli.runtime.awareness_boot import AwarenessState
    live_index.add(pack)
    line = AwarenessState._live_self_model(SimpleNamespace(capability_count=0, _running_version=lambda: ""))
    assert "1 documents read and indexed (50 passages)" in line


def test_when_the_block_is_too_small_the_best_passages_are_the_ones_kept():
    """Live: the block was cut in page order, so a 35-part policy showed parts 1 and 2 and
    dropped part 26, the one that answered the question."""
    def hit(part, text):
        return {"meta": {"doc_id": 1, "title": "policy.md", "part": part, "parts": 35, "where": "", "text": text}}
    hits = [hit(26, "A serious incident must be reported within 2 days. " * 8),
            hit(1, "Scope and definitions. " * 20), hit(2, "Roles of the provider. " * 20),
            hit(30, "Penalties apply.")]
    block = di.format_passages(hits, max_chars=900)
    assert "part 26 of 35" in block and "within 2 days" in block
    assert "part 1 of 35" not in block           # no room for it once the best is in
    assert block.splitlines()[1].startswith("[policy.md | part 26 of 35]")  # best first: the tail is what gets trimmed


def test_passages_that_open_alike_are_not_taken_for_copies_of_each_other():
    """Live: the prompt de-duplicator keys a line by its first words. Passage 26 of a policy
    opened like passage 25 (they overlap) and was dropped; it was the one with the answer."""
    from eli.cognition.prompt_dedupe import dedupe_prompt_parts
    opening = "the compliance officer and the results are kept with the audit papers. "
    block = di.format_passages([
        {"meta": {"doc_id": 1, "title": "policy.md", "part": 25, "parts": 35, "where": "", "text": opening + "Section 9 covers timelines."}},
        {"meta": {"doc_id": 1, "title": "policy.md", "part": 26, "parts": 35, "where": "p. 9",
                  "text": opening + "A serious incident must be reported within 15 days."}},
    ])
    memory, brief = dedupe_prompt_parts(block, "Brief line that is long enough to be keyed by the dedupe.")
    assert "part 25 of 35" in memory and "within 15 days" in memory


def test_one_word_of_a_file_name_in_passing_does_not_pull_the_document_in(index, tmp_path):
    """Live on 2.5.2: "I thought I had a presentation at 10am for <course>" put six passages of a
    coursework file into a chat prompt, because the course name is in the file name."""
    doc = tmp_path / "Sam_Jones_HARBOUR_High_Risk_Use_Case_Definition_Pack_Week_1_summary.md"
    doc.write_text("# Use case pack\n\n" + FILLER + "\n\n" + FACT)
    index.add(doc)
    for said in ("I thought i had a presentation at 10am for HARBOUR, but it is not until 7.30pm haha",
                 "give me a summary of this week", "what a week, high risk of rain"):
        assert not index.mentions(said), said
    assert index.mentions("what does the HARBOUR pack say about biometric identification")
    assert index.mentions("the sam jones harbour work")           # two of the title's own words
    _, planner, _, _ = _orchestrator(index)
    plan = planner.plan_retrieval("I thought i had a presentation at 10am for HARBOUR, but it is not until 7.30pm haha",
                                  {"action": "CHAT"}, "", None, reasoning_mode="quick")
    assert not plan["need_rag"]
