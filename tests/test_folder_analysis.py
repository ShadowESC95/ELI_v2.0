"""Reading a folder: each PDF into the document index (not personal memory), one summary over all of them,
the whole result saved as a document, and progress the job can report."""
import pytest

from eli.runtime import folder_analysis as fa


def test_a_reply_cut_at_its_limit_ends_at_its_last_finished_line():
    assert fa.finished("### Methods\n1. **Action:** variational.\n4.  **") == "### Methods\n1. **Action:** variational."
    assert fa.finished("All done.") == "All done."
    assert fa.finished("The documents outline an attempt to") == "The documents outline an attempt to…"


def test_every_document_reaches_the_summary_however_many_there_are():
    asked = []

    def call(text, tokens):
        asked.append(text)
        return f"summary {len(asked)}."

    titles = [f"### Doc{i}.pdf\n" + "x" * 300 for i in range(12)]
    out = fa._summary(titles, "physics", call, room=len(fa._PART_ASK) + 1000, report=lambda *a: None)
    parts = [a for a in asked if a.startswith("Below are the opening pages")]
    assert len(parts) > 1
    assert all(any(f"Doc{i}.pdf" in p for p in parts) for i in range(12))
    assert asked[-1].startswith("Below are 4 summaries, each of a share of the 12 documents") and "Group" not in asked[-1]
    assert out == f"summary {len(asked)}."


@pytest.fixture
def index(tmp_path, monkeypatch):
    from eli.memory.document_index import DocumentIndex
    idx = DocumentIndex(tmp_path / "documents.sqlite3", embed=lambda text: None)
    monkeypatch.setattr("eli.memory.document_index.get_document_index", lambda: idx)
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path / "data"))
    return idx


def test_a_folder_goes_to_the_document_index_and_a_saved_document(tmp_path, index, monkeypatch):
    folder = tmp_path / "physics"
    folder.mkdir()
    for i in range(3):
        (folder / f"chapter{i}.pdf").write_text(f"Chapter {i} entropy gradient field Xi")
    (folder / "broken.pdf").write_bytes(b"")
    # the reader stands in for pypdf, which the test setup's mocked Pillow keeps from importing
    monkeypatch.setattr("eli.plugins.document_reader.plugin.document_sections",
                        lambda p: [("p. 1", p.read_text())] if p.stat().st_size else [])
    calls, seen = [], []
    monkeypatch.setattr(fa, "_model", lambda: ((lambda text, n: calls.append(text) or "It covers $\\Xi$."), 100_000))
    stored = []
    monkeypatch.setattr("eli.memory.memory.Memory.store_memory", lambda *a, **k: stored.append(a))
    out = fa.analyse(folder, progress=lambda done, total, stage: seen.append((stage, done, total)))
    assert out["count"] == 3 and out["unreadable"] == ["broken.pdf"] and not stored
    assert {d["title"] for d in index.documents()} == {"chapter0.pdf", "chapter1.pdf", "chapter2.pdf"}
    assert all(f"chapter{i}.pdf" in calls[0] for i in range(3))
    assert ("reading", 4, 4) in seen and seen[-1][0] == "summarising"
    assert "## Documents" in out["content"] and "broken.pdf" in out["content"]
    saved = out["document_path"]
    assert saved and (saved.endswith(".pdf") or saved.endswith(".docx"))


def test_installed_software_in_the_folder_is_not_read_as_documents(tmp_path):
    """A physics folder held three virtualenvs: matplotlib's toolbar icons came back as documents."""
    from eli.memory.document_index import document_files
    (tmp_path / "papers").mkdir()
    (tmp_path / "papers" / "thesis.pdf").write_bytes(b"x")
    env = tmp_path / "sims" / "venv-xichi"
    (env / "lib" / "site-packages" / "matplotlib").mkdir(parents=True)
    (env / "pyvenv.cfg").write_text("home = /usr/bin")
    (env / "lib" / "site-packages" / "matplotlib" / "back.pdf").write_bytes(b"x")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "old.pdf").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")
    assert [p.name for p in document_files(tmp_path)] == ["thesis.pdf"]
