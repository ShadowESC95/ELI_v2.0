from __future__ import annotations

from eli.gui.qt_compat import QVBoxLayout, QWidget

from eli.world.renderers.pyside6.world_panel import EliWorldPanel

class EliWorldTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(EliWorldPanel(self))
