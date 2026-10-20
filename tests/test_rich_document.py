"""Formulas typeset and Markdown laid out without a TeX install: chat, task view and saved documents.

The folder summary arrived as raw "$\\Xi$" and "$$ S = \\int ... $$", and a document needed pandoc and LuaLaTeX,
which few machines have."""
import struct

import pytest

from eli.runtime import rich_document as rd

# matplotlib writes PNGs through Pillow, which the main test setup mocks; these run with --noconftest
needs_png = pytest.mark.skipif(not rd.formula_png("x", size_pt=10, dpi=96, color="#000000"),
                               reason="Pillow is mocked here; run with --noconftest")

ACTION = r"S = \int d^4x\sqrt{-g} \left[ \frac{1}{2}f(\Xi)R - \frac{1}{4}F_{\mu\nu}F^{\mu\nu} \right]"


def _html(md):
    return rd.to_html(md, color="#000000", size_pt=10, scale=2.0)


@needs_png
def test_inline_and_display_formulas_become_images_at_the_text_size():
    body, images = _html(f"The field $\\Xi$ couples to $\\chi$.\n\n$${ACTION}$$")
    assert body.count('<img src="eli-formula:') == 3 and len(images) == 3
    assert '<p align="center"><img' in body
    for png in images.values():
        w, h = struct.unpack(">II", png[16:24])
        assert w > 0 and h > 0
    assert "$" not in body


def test_prices_and_code_stay_as_written():
    body, images = _html("It costs $5 and $10. Code `x_1 = $y$` and\n\n```\n$$not maths$$\n```")
    assert not images
    assert "$5 and $10" in body and "$y$" in body and "$$not maths$$" in body


@needs_png
def test_an_aligned_block_is_drawn_row_by_row_and_box_reads():
    body, images = _html(r"$$\begin{aligned} G_{\mu\nu} &= 8\pi G T_{\mu\nu} \\ \Box\Xi &= V'(\Xi) \end{aligned}$$")
    assert len(images) == 2 and "<br>" in body and "<code>" not in body


def test_what_matplotlib_cannot_read_stays_readable_as_source():
    body, images = _html(r"$\notacommand{x}$")
    assert not images and r"<code>\notacommand{x}</code>" in body


def test_markdown_is_laid_out():
    body, _ = _html("## Methods\n\n1. **Action:** variational\n\n| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<h2>Methods</h2>" in body and "<strong>Action:</strong>" in body and '<table border="1"' in body


@needs_png
def test_docx_carries_formulas_as_pictures(tmp_path):
    from docx import Document
    path = rd.write_docx(f"# Summary\n\nWith $\\Xi$:\n\n$${ACTION}$$\n\n- one item", tmp_path / "s.docx", title="T")
    doc = Document(str(path))
    assert len(doc.inline_shapes) == 2
    assert any(p.text == "Summary" for p in doc.paragraphs)


def test_a_pdf_is_written_where_qt_runs(tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    path = rd.write_document(f"## Methods\n\n$${ACTION}$$", tmp_path / "s.pdf", title="physics")
    assert path.suffix == ".pdf" and path.read_bytes().startswith(b"%PDF")


def test_items_the_model_indents_three_spaces_are_nested_not_run_together():
    body, _ = _html("1. **Scalar fields:**\n   - Horndeski class\n   - units listed\n2. **Action:**\n   - total")
    assert body.count("<ul>") == 2 and "<li>Horndeski class</li>" in body and "- units" not in body
