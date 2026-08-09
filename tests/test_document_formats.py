"""Locks on the document formats ELI claims to read.

Two defects motivated this file.

1. `.odt` and `.epub` were advertised but never dispatched. Worse than absent:
   both are zip containers, neither is in `_TEXT_SUFFIXES`, so any such file
   under the 2MB threshold fell through to the plain-text branch and came back
   as decoded zip bytes with ``ok: True`` — mojibake presented as the document's
   contents. A refusal would have been correct; a confident wrong answer is the
   failure mode that matters.

2. Nothing tied the reader's coverage to the formats the README lists, so the
   two could drift apart silently, which is exactly how (1) survived.

Fixtures are built in-test with stdlib zipfile rather than committed binaries:
the point is the container layout, and a checked-in .odt is unreviewable.
"""
import zipfile

import pytest

from eli.plugins.document_reader.plugin import DocumentReaderPlugin, _html_to_text

ODT_CONTENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
  <office:body><office:text>
    <text:h text:outline-level="1">Thermal Budget</text:h>
    <text:p>The absorber runs at <text:span>420</text:span> kelvin.</text:p>
    <text:list><text:list-item><text:p>Nested list paragraph</text:p></text:list-item></text:list>
    <text:p/>
  </office:text></office:body>
</office:document-content>
"""


@pytest.fixture
def plugin():
    return DocumentReaderPlugin()


def _write_odt(path, content_xml=ODT_CONTENT_XML):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", content_xml)
    return path


def _write_epub(path, *, spine=True):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        if spine:
            z.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/book.opf"
     media-type="application/oebps-package+xml"/></rootfiles>
</container>""")
            z.writestr("OEBPS/book.opf", """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <manifest>
    <item id="c2" href="second.xhtml" media-type="application/xhtml+xml"/>
    <item id="c1" href="first.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>""")
        z.writestr("OEBPS/first.xhtml",
                   "<html><head><style>p{color:red}</style></head>"
                   "<body><h1>Chapter One</h1><p>Alpha sentence.</p></body></html>")
        z.writestr("OEBPS/second.xhtml",
                   "<html><body><p>Beta sentence.</p>"
                   "<script>var x=1;</script></body></html>")
    return path


# ── ODT ─────────────────────────────────────────────────────────────────────
def test_odt_text_is_extracted(plugin, tmp_path):
    res = plugin.read({"path": str(_write_odt(tmp_path / "a.odt"))})
    assert res["ok"] is True
    assert "Thermal Budget" in res["content"]
    assert "420 kelvin" in res["content"], "inline text:span must not split the sentence"
    assert "Nested list paragraph" in res["content"]


def test_odt_does_not_return_zip_bytes(plugin, tmp_path):
    """The original bug, stated directly."""
    res = plugin.read({"path": str(_write_odt(tmp_path / "a.odt"))})
    assert "PK" not in res["content"][:4], "raw zip container leaked as document text"
    assert "\x00" not in res["content"]


def test_odt_paragraphs_are_not_double_counted(plugin, tmp_path):
    res = plugin.read({"path": str(_write_odt(tmp_path / "a.odt"))})
    assert res["content"].count("Nested list paragraph") == 1


def test_odt_skips_empty_paragraphs(plugin, tmp_path):
    res = plugin.read({"path": str(_write_odt(tmp_path / "a.odt"))})
    assert "\n\n" not in res["content"], "empty text:p emitted a blank line"


def test_odt_rejects_a_non_zip(plugin, tmp_path):
    p = tmp_path / "fake.odt"
    p.write_bytes(b"this is not a zip file at all")
    res = plugin.read({"path": str(p)})
    assert res["ok"] is False and "zip" in res["error"].lower()


def test_odt_rejects_a_zip_without_content_xml(plugin, tmp_path):
    p = tmp_path / "empty.odt"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
    res = plugin.read({"path": str(p)})
    assert res["ok"] is False and "content.xml" in res["error"]


def test_odt_survives_malformed_xml(plugin, tmp_path):
    res = plugin.read({"path": str(_write_odt(tmp_path / "b.odt", "<office:body><unclosed>"))})
    assert res["ok"] is False, "must report, not raise"


# ── EPUB ────────────────────────────────────────────────────────────────────
def test_epub_text_is_extracted(plugin, tmp_path):
    res = plugin.read({"path": str(_write_epub(tmp_path / "b.epub"))})
    assert res["ok"] is True
    assert "Chapter One" in res["content"]
    assert "Alpha sentence." in res["content"]
    assert "Beta sentence." in res["content"]


def test_epub_is_read_in_spine_order_not_filename_order(plugin, tmp_path):
    """first.xhtml/second.xhtml sort the wrong way round relative to the spine
    only if the spine is ignored — here the spine order and alphabetical order
    agree on first<second, so the manifest is deliberately declared c2-then-c1
    to catch an implementation that walks the manifest instead."""
    res = plugin.read({"path": str(_write_epub(tmp_path / "b.epub"))})
    assert res["content"].index("Alpha") < res["content"].index("Beta")


def test_epub_strips_script_and_style(plugin, tmp_path):
    res = plugin.read({"path": str(_write_epub(tmp_path / "b.epub"))})
    assert "var x=1" not in res["content"]
    assert "color:red" not in res["content"]


def test_epub_falls_back_when_the_opf_is_missing(plugin, tmp_path):
    """A mangled spine should degrade to out-of-order text, not to no text."""
    res = plugin.read({"path": str(_write_epub(tmp_path / "c.epub", spine=False))})
    assert res["ok"] is True
    assert "Alpha sentence." in res["content"]


def test_epub_rejects_a_non_zip(plugin, tmp_path):
    p = tmp_path / "fake.epub"
    p.write_bytes(b"not a zip")
    res = plugin.read({"path": str(p)})
    assert res["ok"] is False


# ── the silent-garbage class of bug, generally ──────────────────────────────
def test_unknown_binary_is_refused_not_decoded(plugin, tmp_path):
    """Any small binary used to sail through the <2MB text branch."""
    p = tmp_path / "thing.pptx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("ppt/presentation.xml", "<p:presentation/>")
    res = plugin.read({"path": str(p)})
    assert res["ok"] is False, "binary decoded as text under ok=True"
    assert res["error"] == "unsupported_format"


def test_known_text_suffixes_still_read(plugin, tmp_path):
    p = tmp_path / "notes.md"
    p.write_text("# Heading\n\nbody text", encoding="utf-8")
    res = plugin.read({"path": str(p)})
    assert res["ok"] is True and "body text" in res["content"]


def test_extensionless_text_still_reads(plugin, tmp_path):
    """The <2MB fallback is what makes README/LICENSE readable; the binary
    guard must not have closed it."""
    p = tmp_path / "LICENSE"
    p.write_text("PolyForm Internal Use", encoding="utf-8")
    res = plugin.read({"path": str(p)})
    assert res["ok"] is True and "PolyForm" in res["content"]


# ── html extraction unit ────────────────────────────────────────────────────
def test_html_to_text_separates_block_elements():
    assert _html_to_text("<p>one</p><p>two</p>").splitlines() == ["one", "two"]


def test_html_to_text_resolves_entities():
    assert "AT&T" in _html_to_text("<p>AT&amp;T</p>")


def test_html_to_text_survives_malformed_markup():
    _html_to_text("<p>unclosed <b>bold")   # must not raise


# ── coverage matches what is advertised ─────────────────────────────────────
def test_plugin_description_lists_the_formats_it_dispatches():
    """(2): the description is the user-facing claim, so drift shows up here."""
    desc = DocumentReaderPlugin.description.lower()
    for fmt in ("pdf", "docx", "odt", "epub"):
        assert fmt in desc, f"{fmt} is dispatched but not advertised"
