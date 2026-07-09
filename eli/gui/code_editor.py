"""Native code editor for the IDE — PySide6/PyQt, no QScintilla required.

QScintilla (Riverbank) ships PyQt bindings only, and mixing PyQt's Qt runtime
into a PySide6 process is not safe, so the shipped LGPL PySide6 stack can never
load Qsci. This module provides the IDE editor natively instead: line-number
margin, current-line highlight, Python syntax highlighting, and auto-indent on
top of QPlainTextEdit — same document API (`setPlainText` / `toPlainText` /
`clear`) as the old basic fallback, plus Qsci-style `text()` / `setText()`
aliases so either call convention works.
"""

try:
    from PySide6.QtWidgets import QPlainTextEdit, QWidget, QTextEdit
    from PySide6.QtCore import Qt, QRect, QSize
    from PySide6.QtGui import (QColor, QPainter, QTextFormat, QFont,
                               QSyntaxHighlighter, QTextCharFormat)
except ImportError:  # pragma: no cover - PyQt fallbacks mirror the main GUI
    try:
        from PyQt6.QtWidgets import QPlainTextEdit, QWidget, QTextEdit
        from PyQt6.QtCore import Qt, QRect, QSize
        from PyQt6.QtGui import (QColor, QPainter, QTextFormat, QFont,
                                 QSyntaxHighlighter, QTextCharFormat)
    except ImportError:
        from PyQt5.QtWidgets import QPlainTextEdit, QWidget, QTextEdit
        from PyQt5.QtCore import Qt, QRect, QSize
        from PyQt5.QtGui import (QColor, QPainter, QTextFormat, QFont,
                                 QSyntaxHighlighter, QTextCharFormat)

import re


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class PythonHighlighter(QSyntaxHighlighter):
    """Regex-rule Python highlighter with triple-quoted-string block states."""

    _KEYWORDS = (
        "False None True and as assert async await break class continue def del "
        "elif else except finally for from global if import in is lambda nonlocal "
        "not or pass raise return try while with yield match case"
    ).split()
    _BUILTINS = (
        "abs all any bin bool bytes callable chr classmethod compile complex dict "
        "dir divmod enumerate eval exec filter float format frozenset getattr "
        "globals hasattr hash help hex id input int isinstance issubclass iter len "
        "list locals map max min next object oct open ord pow print property range "
        "repr reversed round set setattr slice sorted staticmethod str sum super "
        "tuple type vars zip Exception BaseException ValueError TypeError KeyError "
        "IndexError RuntimeError StopIteration NotImplementedError OSError"
    ).split()

    def __init__(self, document):
        super().__init__(document)
        kw = "|".join(self._KEYWORDS)
        bi = "|".join(self._BUILTINS)
        self._rules = [
            (re.compile(rf"\b(?:{kw})\b"), _fmt("#c678dd", bold=True)),
            (re.compile(rf"\b(?:{bi})\b"), _fmt("#56b6c2")),
            (re.compile(r"\bself\b|\bcls\b"), _fmt("#e06c75", italic=True)),
            (re.compile(r"(?<=\bdef\s)\w+|(?<=\bclass\s)\w+"), _fmt("#61afef", bold=True)),
            (re.compile(r"@\w[\w.]*"), _fmt("#d19a66")),
            (re.compile(r"\b\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?\b|\b0[xXbBoO][\da-fA-F_]+\b"),
             _fmt("#d19a66")),
            (re.compile(r"(?:[rbuf]{0,2})'(?:[^'\\]|\\.)*'|(?:[rbuf]{0,2})\"(?:[^\"\\]|\\.)*\"",
                        re.IGNORECASE), _fmt("#98c379")),
            (re.compile(r"#[^\n]*"), _fmt("#5c6370", italic=True)),
        ]
        self._tri_fmt = _fmt("#98c379")
        self._tri_open = re.compile(r"(?:[rbuf]{0,2})('''|\"\"\")", re.IGNORECASE)

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)

        # Triple-quoted strings across blocks. State: 0/-1 none, 1 in ''', 2 in """.
        self.setCurrentBlockState(0)
        pos = 0
        state = self.previousBlockState()
        if state in (1, 2):
            quote = "'''" if state == 1 else '"""'
            end = text.find(quote)
            if end == -1:
                self.setFormat(0, len(text), self._tri_fmt)
                self.setCurrentBlockState(state)
                return
            self.setFormat(0, end + 3, self._tri_fmt)
            pos = end + 3
        while True:
            m = self._tri_open.search(text, pos)
            if not m:
                break
            quote = m.group(1)
            end = text.find(quote, m.end())
            if end == -1:
                self.setFormat(m.start(), len(text) - m.start(), self._tri_fmt)
                self.setCurrentBlockState(1 if quote == "'''" else 2)
                return
            self.setFormat(m.start(), end + 3 - m.start(), self._tri_fmt)
            pos = end + 3


class _LineNumberArea(QWidget):
    def __init__(self, editor: "PyCodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor._line_number_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor._paint_line_numbers(event)


class PyCodeEditor(QPlainTextEdit):
    """Drop-in IDE editor: line numbers, current-line highlight, Python
    highlighting, auto-indent, 4-space tabs. API-compatible with both the old
    QTextEdit fallback (setPlainText/toPlainText) and Qsci calls (text/setText)."""

    def __init__(self, parent=None, highlight: bool = True):
        super().__init__(parent)
        font = QFont("Courier New", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._line_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_line_area_width()
        self._highlight_current_line()

        if highlight:
            self._highlighter = PythonHighlighter(self.document())

    # Qsci-style aliases so QSCI-written call sites keep working.
    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self.setPlainText(text)

    # ── line-number margin ───────────────────────────────────────────────
    def _line_number_width(self) -> int:
        digits = max(3, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_area_width(self, _new_count: int = 0) -> None:
        self.setViewportMargins(self._line_number_width(), 0, 0, 0)

    def _update_line_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(QRect(cr.left(), cr.top(),
                                          self._line_number_width(), cr.height()))

    def _paint_line_numbers(self, event) -> None:
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor("#171b24"))
        block = self.firstVisibleBlock()
        block_no = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        painter.setPen(QColor("#5c6370"))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(0, top, self._line_area.width() - 6,
                                 self.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, str(block_no + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_no += 1
        painter.end()

    # ── current-line highlight ───────────────────────────────────────────
    def _highlight_current_line(self) -> None:
        if self.isReadOnly():
            self.setExtraSelections([])
            return
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor("#1e2a3a"))
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])

    # ── auto-indent + spaces-for-tab ─────────────────────────────────────
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Tab and not event.modifiers():
            self.insertPlainText("    ")
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            cursor = self.textCursor()
            line = cursor.block().text()[:cursor.positionInBlock()]
            indent = line[:len(line) - len(line.lstrip())]
            if line.rstrip().endswith(":"):
                indent += "    "
            super().keyPressEvent(event)
            self.insertPlainText(indent)
            return
        super().keyPressEvent(event)
