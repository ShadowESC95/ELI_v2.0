
"""
Proactive Dock GUI
Separate channel for proactive cognition.
"""
from PyQt5 import QtWidgets, QtCore

class ProactiveDock(QtWidgets.QDockWidget):
    def __init__(self, parent=None):
        super().__init__("ELI Proactive", parent)
        self.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        self.text = QtWidgets.QTextEdit()
        self.text.setReadOnly(True)
        self.tts_toggle = QtWidgets.QCheckBox("Read aloud responses")
        self.tts_toggle.setChecked(True)
        layout.addWidget(self.text)
        layout.addWidget(self.tts_toggle)
        self.setWidget(widget)

    def post_message(self, msg: str):
        self.text.append(msg)
