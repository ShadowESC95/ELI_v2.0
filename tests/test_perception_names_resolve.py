"""Two perception paths imported names that do not exist and failed silently."""
import time

from eli.memory.memory import Memory
from eli.perception import analyze_pdfs, audio_stt, wakeword


def test_pdf_analysis_lands_in_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_TEST_MODE", "1")
    monkeypatch.setattr("eli.memory.vector_store.get_vector_store", lambda: None)
    doc = analyze_pdfs.PDFDoc(path="/docs/report.pdf", pages=3, chars=900, sha1="ab12cd34ef56aa", extracted_at=time.time())
    analysis = analyze_pdfs.PDFAnalysis(doc=doc, preview="Quarterly totals for the harbour project",
                                        chunks=["first chunk about tides", "second chunk about moorings"], warnings=[])
    db = tmp_path / "user.sqlite3"
    out = analyze_pdfs.store_analysis_to_memory(db, analysis)
    assert out == {"ok": True, "doc_id": "ab12cd34ef56", "chunks": 2}
    found = " ".join(h["text"] for h in Memory(db_path=db).recall_memory("harbour tides moorings", limit=10))
    assert "harbour project" in found and "tides" in found


def test_stt_diagnostics_reports_the_wake_phrase(monkeypatch):
    monkeypatch.setattr(wakeword, "is_trained", lambda: True)
    monkeypatch.setattr(wakeword, "get_wake_phrases", lambda: ["hey eli"])
    out = audio_stt.stt_diagnostics()
    assert out["wake_model_trained"] is True and out["wake_phrase"] == "hey eli"
