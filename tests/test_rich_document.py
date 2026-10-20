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


def _font():
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    return QFont()


def _html(md):
    return rd.to_html(md, color="#000000", font=_font(), scale=2.0)


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
    from docx.oxml.ns import qn
    path = rd.write_docx(f"# Summary\n\nWith $\\Xi$:\n\n$${ACTION}$$\n\n- one item", tmp_path / "s.docx", title="T")
    doc = Document(str(path))
    assert len(doc.inline_shapes) == 2
    assert any(p.text == "Summary" for p in doc.paragraphs)
    # Word stands a picture on the baseline: each is lowered by the depth it was drawn with below its own
    path = rd.write_docx("Mass $m_\\gamma$ and $x$.", tmp_path / "d.docx")
    shifts = [r._r.rPr.find(qn("w:position")) for r in Document(str(path)).paragraphs[0].runs if r._r.rPr is not None]
    drawn = [-round(rd._box(t, 11.0)[2] * 2) for t in (r"m_\gamma", "x")]
    assert [int(e.get(qn("w:val"))) for e in shifts if e is not None] == [d for d in drawn if d]
    assert drawn[0] < 0


def test_a_pdf_is_written_where_qt_runs(tmp_path):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    before = app.palette()
    dark = QPalette(before)
    dark.setColor(QPalette.ColorRole.Text, QColor("#e0e0e0"))
    app.setPalette(dark)            # ELI's window theme; drawn with it, the PDF's text came out near white
    try:
        path = rd.write_document(f"## Methods\n\n$${ACTION}$$" + "\n\nline" * 400, tmp_path / "s.pdf", title="physics")
    finally:
        app.setPalette(before)
    data = path.read_bytes()
    assert path.suffix == ".pdf" and data.startswith(b"%PDF") and data.count(b"/Type /Page\n") > 1
    QtPdf = pytest.importorskip("PySide6.QtPdf")
    pdf = QtPdf.QPdfDocument()
    pdf.load(str(path))
    page = pdf.render(0, QSize(400, 560))
    ink = [(x, c) for y in range(page.height()) for x in range(page.width())
           if (c := page.pixelColor(x, y)).alpha() > 128]
    assert ink and all(c.lightness() < 160 for _, c in ink)
    # a tenth of the page width clear each side (QPdfWriter's own 10 pt margins had left 4 mm)
    assert min(x for x, _ in ink) >= page.width() / 10 - 1 and max(x for x, _ in ink) <= page.width() * 9 / 10 + 1
    # the page number, at the text's size: its point size was applied at 1200 dpi and then zoomed (150 pt tall)
    rows = sorted({y for y in range(page.height()) for x in range(page.width() * 3 // 4, page.width())
                   if page.pixelColor(x, y).alpha() > 128 and y > page.height() * 3 // 4})
    assert rows and rows[-1] - rows[0] < page.height() / 40


@needs_png
def test_a_formula_is_as_large_as_the_text_and_stands_on_its_baseline():
    """Computer Modern's x is a smaller share of its size than a sans font's, so formulas drawn at the
    text's size looked a size smaller; and Qt's "middle" image alignment centred them in the line box,
    a third of an x-height above the baseline."""
    import io
    from PIL import Image
    from PySide6.QtGui import QFontMetricsF, QTextCharFormat, QTextDocument
    font = _font()
    m = QFontMetricsF(font)
    size, descent = rd.text_metrics(font)
    dpi = m.fontDpi() * 10
    ink = Image.open(io.BytesIO(rd.formula_png("x", size_pt=size, dpi=dpi, color="#000000"))).getchannel("A")
    top, bottom = ink.point(lambda a: 255 if a > 127 else 0).getbbox()[1::2]
    assert abs((bottom - top) - m.xHeight() * 10) <= 10 * 0.5 + 2          # same x, to a layout pixel

    doc = QTextDocument()
    doc.setDefaultFont(font)
    body, images = rd.to_html("Mass $m_\\gamma$ and $x$, $\\frac{a}{b}$.", color="#000000", font=font, scale=1.0)
    rd.put_html(doc, body, images)
    seated = []
    it = doc.begin().begin()
    while not it.atEnd():
        fmt = it.fragment().charFormat()
        if fmt.isImageFormat():
            fm = QFontMetricsF(fmt.font())
            seated.append((fmt.verticalAlignment(), fm.descent() * 72 / fm.fontDpi(), rd._BASELINE[fmt.toImageFormat().name()]))
        it += 1
    assert len(seated) == 3
    for align, below, baseline in seated:
        assert align == QTextCharFormat.VerticalAlignment.AlignBaseline
        assert abs(below - baseline) <= baseline * 0.1 and baseline >= descent


def test_a_fraction_standing_in_a_displayed_formula_is_full_size():
    assert rd._display(r"\frac{1}{2}f - \frac{a}{\frac{b}{c}}") == r"\dfrac{1}{2}f - \dfrac{a}{\frac{b}{c}}"
    assert rd._display(r"\{\fracture\}") == r"\{\fracture\}"


def test_items_the_model_indents_three_spaces_are_nested_not_run_together():
    body, _ = _html("1. **Scalar fields:**\n   - Horndeski class\n   - units listed\n2. **Action:**\n   - total")
    assert body.count("<ul>") == 2 and "<li>Horndeski class</li>" in body and "- units" not in body
