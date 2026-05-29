"""Shared Qt import shim for eli.gui.panels modules.

All panel modules import from here so the PySide6-first / PyQt5-fallback
logic is maintained in one place.
"""
from __future__ import annotations

try:
    from PySide6.QtWidgets import *
    from PySide6.QtCore import *
    from PySide6.QtGui import *
    pyqtSignal = Signal
    pyqtSlot = Slot
    QT_API = "PySide6"
except ImportError:
    try:
        from PyQt6.QtWidgets import *
        from PyQt6.QtCore import *
        from PyQt6.QtGui import *
        from PyQt6.QtCore import pyqtSignal
        QT_API = "PyQt6"
    except ImportError:
        from PyQt5.QtWidgets import *
        from PyQt5.QtCore import *
        from PyQt5.QtGui import *
        from PyQt5.QtCore import pyqtSignal
        QT_API = "PyQt5"

from datetime import datetime


def now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")
