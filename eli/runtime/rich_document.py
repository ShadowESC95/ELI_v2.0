"""Markdown with LaTeX maths, typeset without a TeX installation.

matplotlib draws each formula (its mathtext reads the common LaTeX maths), Python-Markdown lays out the
text and Qt writes the PDF; all three ship in every ELI build, while pandoc and LuaLaTeX, which the
older export path needs, are on few machines. The chat, the task view and saved documents use the same
rendering, so a formula reads the same everywhere.
"""
from __future__ import annotations

import functools
import hashlib
import html
import io
import re
import struct
import threading
from pathlib import Path
from typing import Dict, List, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

_DISPLAY = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.S)
# $x$ but not prices: no space inside either dollar, no digit or letter right after the closing one
_INLINE = re.compile(r"\\\((.+?)\\\)|(?<![\\$\w])\$(?=\S)([^$\n]+?)(?<=\S)\$(?![\w$])")
_ENV = re.compile(r"\\begin\{(\w+)\*?\}(.*?)\\end\{\1\*?\}", re.S)
_CODE = re.compile(r"```.*?```|`[^`\n]+`", re.S)
_DRAW_LOCK = threading.Lock()      # matplotlib's text engine keeps global state
_RC = {"mathtext.fontset": "cm"}   # Computer Modern, as TeX sets maths
_MATHS_ITALIC = "cmmi10"           # its maths italic, whose x sets how large the letters look
_BASELINE: Dict[str, float] = {}   # formula image -> its baseline's height above its lower edge (pt)
# LaTeX commands mathtext lacks, written with ones it has
_SPELLINGS = ((r"\Box", "\u25a1"), (r"\boldsymbol", r"\mathbf"), (r"\bm", r"\mathbf"),
              (r"\lvert", "|"), (r"\rvert", "|"), (r"\lVert", r"\Vert"), (r"\rVert", r"\Vert"),
              (r"\coloneqq", ":="), (r"\tfrac", r"\frac"))


def has_markup(text: str) -> bool:
    """Formulas, or Markdown worth laying out (headings, emphasis, lists, tables)."""
    t = str(text or "")
    return bool(_DISPLAY.search(t) or _INLINE.search(t)
                or re.search(r"(?m)^\s{0,3}(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|\|.*\|)|\*\*[^*\n]+\*\*", t))


def _spelled(tex: str) -> str:
    for latex, mathtext_name in _SPELLINGS:
        tex = re.sub(re.escape(latex) + r"(?![A-Za-z])", lambda _m: mathtext_name, tex)
    return tex


@functools.lru_cache(maxsize=None)
def _box(tex: str, size_pt: float) -> Tuple[float, float, float]:
    """Width, height and depth below the baseline, in points, as matplotlib lays the formula out."""
    from matplotlib import rc_context
    from matplotlib.font_manager import FontProperties
    from matplotlib.mathtext import MathTextParser
    with _DRAW_LOCK, rc_context(_RC):
        width, height, depth, _, _ = MathTextParser("path").parse(f"${_spelled(tex)}$", dpi=72,
                                                                  prop=FontProperties(size=size_pt))
    return float(width), float(height), float(depth)


@functools.lru_cache(maxsize=None)
def formula_png(tex: str, *, size_pt: float, dpi: float, color: str, below: float = 0.0) -> bytes:
    """One formula as a PNG, or b"" when matplotlib cannot read it. Its baseline sits `below` points
    above the lower edge, or lower where the formula reaches further down."""
    try:
        from matplotlib import rc_context
        from matplotlib.figure import Figure
        from matplotlib.font_manager import FontProperties
        width, height, depth = _box(tex, size_pt)
        room = max(depth, below)
        tall = height - depth + room
        buf = io.BytesIO()
        with _DRAW_LOCK, rc_context({**_RC, "savefig.transparent": True}):
            fig = Figure(figsize=(width / 72.0, tall / 72.0))
            fig.text(0, room / tall, f"${_spelled(tex)}$", fontproperties=FontProperties(size=size_pt), color=color)
            fig.savefig(buf, dpi=dpi, format="png")
        return buf.getvalue()
    except Exception as exc:
        log.debug("formula left as source (%s): %s", str(exc).strip().splitlines()[-1][:120], tex[:80])
        return b""


@functools.lru_cache(maxsize=None)
def _maths_x_height() -> float:
    """The maths italic's x as a share of the font size, read from the font file; 0 if it can't be read."""
    try:
        from matplotlib import ft2font
        from matplotlib.font_manager import FontProperties, findfont
        face = ft2font.FT2Font(findfont(FontProperties(family=_MATHS_ITALIC), fallback_to_default=False))
        no_scale = ft2font.LoadFlags.NO_SCALE if hasattr(ft2font, "LoadFlags") else ft2font.LOAD_NO_SCALE
        return face.load_char(ord("x"), flags=no_scale).bbox[3] / face.units_per_EM
    except Exception:
        log.debug("maths font not measured; formulas at the text's size", exc_info=True)
        return 0.0


def text_metrics(font) -> Tuple[float, float]:
    """For text in `font` (a QFont): the maths size whose x stands as tall as the text's, and how far the
    text reaches below its baseline, in points. Computer Modern's x is a smaller share of its size than
    most text fonts' (0.44 against about 0.54 for common sans fonts), so formulas at the text's own size
    looked a size smaller than the words around them."""
    from PySide6.QtGui import QFontMetricsF
    m = QFontMetricsF(font)
    pt = 72.0 / m.fontDpi()
    maths_x = _maths_x_height()
    size = m.xHeight() * pt / maths_x if maths_x else (font.pointSizeF() if font.pointSizeF() > 0
                                                         else font.pixelSize() * pt)
    return size, m.descent() * pt


def _png_size(png: bytes) -> Tuple[int, int]:
    return struct.unpack(">II", png[16:24])


def _rows(tex: str) -> List[str]:
    """An aligned block (aligned, align, gather, equation, split) one row at a time: mathtext reads
    single expressions only."""
    m = _ENV.search(tex)
    if not m:
        return [tex]
    rows = [r.replace("&", " ").strip() for r in re.split(r"\\\\", m.group(2))]
    return [r for r in rows if r]


def _display(tex: str) -> str:
    """TeX sets a fraction standing in a displayed formula at full size; mathtext draws every \\frac at
    the in-line size unless it is written \\dfrac. Fractions inside others stay small, as in TeX."""
    out: List[str] = []
    depth = i = 0
    while i < len(tex):
        command = re.match(r"\\(?:[A-Za-z]+|.)", tex[i:])
        if command:
            word = command.group(0)
            out.append(r"\dfrac" if word == r"\frac" and depth == 0 else word)
            i += len(word)
            continue
        depth += {"{": 1, "}": -1}.get(tex[i], 0)
        out.append(tex[i])
        i += 1
    return "".join(out)


def to_html(md: str, *, color: str, font, scale: float) -> Tuple[str, Dict[str, bytes]]:
    """HTML for a Qt text document, and the formula images it names (url -> PNG).

    `font` is the text's QFont: formulas are sized to it and sit on its baseline. `scale` is device
    pixels per layout pixel (a 96 dpi page), so formulas stay sharp on the screen or page they are
    drawn for."""
    size_pt, descent = text_metrics(font)
    images: Dict[str, bytes] = {}
    slots: List[str] = []
    codes: List[str] = []

    def stash_code(m):
        codes.append(m.group(0))
        return f"ELICODESLOT{len(codes) - 1}X"

    def formula(tex: str) -> str:
        tex = tex.strip()
        png = formula_png(tex, size_pt=size_pt, dpi=96.0 * scale, color=color, below=descent)
        if not png:
            return f"<code>{html.escape(tex)}</code>"
        url = "eli-formula:" + hashlib.sha1(png).hexdigest()[:16]
        images[url] = png
        _BASELINE[url] = max(descent, _box(tex, size_pt)[2])
        w, h = _png_size(png)
        return f'<img src="{url}" width="{max(1, round(w / scale))}" height="{max(1, round(h / scale))}">'

    def display(m):
        tex = m.group(1) or m.group(2) or ""
        slots.append("<br>".join(formula(_display(r)) for r in _rows(tex)))
        return f"\n\nELIMATHSLOT{len(slots) - 1}D\n\n"

    def inline(m):
        slots.append(formula(m.group(1) or m.group(2) or ""))
        return f"ELIMATHSLOT{len(slots) - 1}X"

    text = _CODE.sub(stash_code, str(md or ""))
    text = _DISPLAY.sub(display, text)
    text = _INLINE.sub(inline, text)
    text = _nest_lists(text)
    # Markdown starts a list only after a blank line; replies often put one straight under a sentence
    text = re.sub(r"(?m)^(?!\s*(?:[-*+]|\d+[.)])\s)(\S.*)\n(?=\s{0,3}(?:[-*+]|\d+[.)])\s)", r"\1\n\n", text)
    text = re.sub(r"ELICODESLOT(\d+)X", lambda m: codes[int(m.group(1))], text)
    try:
        import markdown
        body = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    except Exception:
        log.debug("markdown unavailable; plain paragraphs", exc_info=True)
        body = "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in text.split("\n\n"))
    body = body.replace("<table>", '<table border="1" cellspacing="0" cellpadding="4">')
    body = re.sub(r"<p>\s*ELIMATHSLOT(\d+)D\s*</p>",
                  lambda m: f'<p align="center">{slots[int(m.group(1))]}</p>', body)
    body = re.sub(r"ELIMATHSLOT(\d+)[DX]", lambda m: slots[int(m.group(1))], body)
    return body, images


_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def _nest_lists(text: str) -> str:
    """Items indented two or three spaces under another item are its children; Markdown wants four
    and otherwise runs them into the parent's line."""
    out: List[str] = []
    in_list = False
    for line in text.split("\n"):
        m = re.match(r"^ {1,3}((?:[-*+]|\d+[.)])\s.*)$", line)
        if m and in_list:
            line = "    " + m.group(1)
        if line.strip():
            in_list = bool(_ITEM.match(line)) or (in_list and line.startswith(" "))
        out.append(line)
    return "\n".join(out)


def put_html(document, body: str, images: Dict[str, bytes], cursor=None) -> None:
    """Lay `to_html` output into a QTextDocument (at `cursor`, else as its whole content) with each formula
    standing on the text's baseline.

    Qt's HTML reader can only centre an image on the line, whose box moves with whatever else the line
    holds, or stand its lower edge on the baseline, which lifts anything reaching below it (a subscript,
    a fraction). Its AlignBaseline, set only from code, puts the lower edge the format font's descent
    below the baseline; that font is sized so its descent is the depth the formula was drawn with."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QFontMetricsF, QImage, QTextCharFormat, QTextCursor, QTextDocument
    for url, png in images.items():
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), QImage.fromData(png))
    start = cursor.position() if cursor is not None else 0
    if cursor is not None:
        cursor.insertHtml(body)
        end = cursor.position()
    else:
        document.setHtml(body)
        end = document.characterCount()
    found = []
    block = document.findBlock(start)
    while block.isValid() and block.position() <= end:
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            fmt = frag.charFormat()
            if fmt.isImageFormat() and fmt.toImageFormat().name() in _BASELINE:
                found.append((frag.position(), frag.length(), fmt.toImageFormat()))
            it += 1
        block = block.next()
    edit = QTextCursor(document)
    for pos, length, fmt in found:
        font = fmt.font()
        m = QFontMetricsF(font)
        descent = m.descent() * 72.0 / m.fontDpi()
        if descent <= 0:
            continue
        grow = _BASELINE[fmt.name()] / descent
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * grow)
        else:
            font.setPixelSize(max(1, round(font.pixelSize() * grow)))
        fmt.setFont(font)
        fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignBaseline)
        edit.setPosition(pos)
        edit.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
        edit.setCharFormat(fmt)


def _page_size():
    from PySide6.QtCore import QLocale
    from PySide6.QtGui import QPageSize
    us = QLocale.system().measurementSystem() == QLocale.MeasurementSystem.ImperialUSSystem
    return QPageSize(QPageSize.PageSizeId.Letter if us else QPageSize.PageSizeId.A4)


def write_pdf(md: str, path, *, title: str = "") -> Path:
    """The document as a PDF, laid out by Qt. Needs the Qt application of the ELI window.

    Laid out at the resolution text is measured in, as on screen, and drawn page by page: QTextDocument's
    own print() re-lays an unpaged document out in printer units, where an inline image's baseline is
    still measured in screen pixels (a twelfth of the distance at 1200 dpi), and adds 2 cm margins of
    its own inside the page's."""
    from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
    from PySide6.QtGui import (QAbstractTextDocumentLayout, QColor, QFont, QFontMetricsF, QGuiApplication,
                               QPageLayout, QPainter, QPalette, QPdfWriter, QTextDocument)
    if QGuiApplication.instance() is None:
        raise RuntimeError("no Qt application in this process")
    path = Path(path)
    writer = QPdfWriter(str(path))
    writer.setPageSize(_page_size())
    # a tenth of the width each side (QPdfWriter starts with 10 pt margins, so a check for none never set it)
    side = writer.pageLayout().fullRect(QPageLayout.Unit.Millimeter).width() / 10
    writer.setPageMargins(QMarginsF(side, side, side, side), QPageLayout.Unit.Millimeter)
    writer.setTitle(title or path.stem)
    writer.setCreator("ELI")
    doc = QTextDocument()
    font = doc.defaultFont()
    metrics = QFontMetricsF(font)
    dpi = metrics.fontDpi()
    zoom = writer.resolution() / dpi
    area = writer.pageLayout().paintRect(QPageLayout.Unit.Inch)
    foot = 2 * metrics.lineSpacing()                     # the page number, and a line clear above it
    doc.setPageSize(QSizeF(area.width() * dpi, area.height() * dpi - foot))
    body, images = to_html(md, color="#000000", font=font, scale=zoom)
    put_html(doc, (f"<h1>{html.escape(title)}</h1>" if title else "") + body, images)
    page = doc.pageSize()
    paper = QAbstractTextDocumentLayout.PaintContext()
    paper.palette.setColor(QPalette.ColorRole.Text, QColor("black"))    # the window's dark theme is not the page's
    numbers = QFont(font)          # the painter sizes points at the printer's resolution, before the zoom
    numbers.setPointSizeF((font.pointSizeF() if font.pointSizeF() > 0 else font.pixelSize() * 72.0 / dpi) / zoom)
    painter = QPainter(writer)
    try:
        painter.scale(zoom, zoom)
        painter.setFont(numbers)
        painter.setPen(QColor("black"))
        for n in range(doc.pageCount()):
            if n:
                writer.newPage()
            painter.save()
            painter.translate(0, -n * page.height())
            paper.clip = QRectF(0, n * page.height(), page.width(), page.height())
            painter.setClipRect(paper.clip)
            doc.documentLayout().draw(painter, paper)
            painter.restore()
            painter.drawText(QRectF(0, page.height(), page.width(), foot),
                             int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom), str(n + 1))
    finally:
        painter.end()
    return path


def write_docx(md: str, path, *, title: str = "") -> Path:
    """The document as .docx: headings, lists and paragraphs, formulas as pictures."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt
    path = Path(path)
    doc = Document()
    size = doc.styles["Normal"].font.size or Pt(11)
    if title:
        doc.add_heading(title, level=0)

    def picture(par, tex: str, source: str) -> None:
        tex = tex.strip()
        png = formula_png(tex, size_pt=size.pt, dpi=300.0, color="#000000")
        if not png:
            par.add_run(source)
            return
        run = par.add_run()
        run.add_picture(io.BytesIO(png), height=Pt(_png_size(png)[1] * 72.0 / 300.0))
        # Word stands a picture on the baseline: lowered by the formula's depth, the two baselines meet
        lower = round(_box(tex, size.pt)[2] * 2)          # w:position counts half-points
        if lower:
            shift = OxmlElement("w:position")
            shift.set(qn("w:val"), str(-lower))
            run._r.get_or_add_rPr().append(shift)

    def runs(par, text: str) -> None:
        pos = 0
        for m in _INLINE.finditer(text):
            _words(par, text[pos:m.start()])
            picture(par, m.group(1) or m.group(2) or "", m.group(0))
            pos = m.end()
        _words(par, text[pos:])

    text = _DISPLAY.sub(lambda m: "\n\nELIDISPLAY" + (m.group(1) or m.group(2) or "").replace("\n", " ") + "\n\n",
                        str(md or ""))
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if block.startswith("ELIDISPLAY"):
            for row in _rows(block[len("ELIDISPLAY"):]):
                par = doc.add_paragraph()
                par.alignment = WD_ALIGN_PARAGRAPH.CENTER
                picture(par, row, row)
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", block)
        if heading and "\n" not in block:
            doc.add_heading(heading.group(2).strip(), level=min(len(heading.group(1)), 4))
            continue
        for line in block.split("\n"):
            item = re.match(r"^\s*(?:([-*+])|(\d+)[.)])\s+(.*)$", line)
            if item:
                par = doc.add_paragraph(style="List Bullet" if item.group(1) else "List Number")
                runs(par, item.group(3))
            else:
                runs(doc.add_paragraph(), line.strip())
    doc.save(str(path))
    return path


def _words(par, text: str) -> None:
    """Text with **bold** and *italic*."""
    for part in re.split(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)", text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            par.add_run(part[2:-2]).bold = True
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            par.add_run(part[1:-1]).italic = True
        else:
            par.add_run(part)


def write_document(md: str, path, *, title: str = "") -> Path:
    """PDF where Qt can lay it out, .docx otherwise (a server with no window); returns where it went."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        try:
            return write_pdf(md, path, title=title)
        except Exception:
            log.debug("PDF not written; writing .docx", exc_info=True)
            path = path.with_suffix(".docx")
    return write_docx(md, path, title=title)
