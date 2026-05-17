"""
Proactive Dock GUI
Separate channel for proactive cognition.
"""
from eli.gui import qt_compat as QtCompat

Qt = QtCompat.Qt


class ProactiveDock(QtCompat.QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ELI Proactive")
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        widget = QtCompat.QWidget()
        layout = QtCompat.QVBoxLayout(widget)
        self.text = QtCompat.QTextEdit()
        self.text.setReadOnly(True)
        self.tts_toggle = QtCompat.QCheckBox("Read aloud visible proactive messages")
        self.tts_toggle.setChecked(False)
        layout.addWidget(self.text)
        layout.addWidget(self.tts_toggle)
        self.setWidget(widget)

    def post_message(self, msg: str):
        self.text.append(msg)
