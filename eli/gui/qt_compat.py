"""Qt binding compatibility shim.

Import policy: PySide6 → PyQt6 → PyQt5 → headless stubs.

Why PySide6 first
-----------------
PySide6 is licensed under LGPLv3. LGPL allows dynamic linking from
proprietary code (which is what Python always does), so a closed-source
or differently-licensed binary that links PySide6 stays compliant
without forcing the entire product to be GPL.

PyQt6 is GPLv3. If ELI imports PyQt6 in its shipped binary, the binary
inherits GPLv3 obligations: source must be made available, derivative
works must also be GPL, and any redistribution path including
proprietary forks is blocked. The project therefore ships PySide6
exclusively via `requirements*.txt` and `pyproject.toml`.

The PyQt6 / PyQt5 fallback paths exist only so users who already have
those bindings installed can run from source without adding a second
Qt binding. They are not shipped, packaged, or recommended. If you are
distributing ELI commercially or in a closed-source form, ensure your
runtime environment uses PySide6 (the default) and not PyQt.

The headless stub branch keeps the surface importable in test and audit
environments where no Qt binding is present at all.

Symbol naming
-------------
PySide6 exposes signals and slots as ``Signal`` / ``Slot``. The shim
re-exports them as ``pyqtSignal`` / ``pyqtSlot`` so call sites can use
a single name across all three bindings without conditional imports.
"""

from __future__ import annotations

QT_API = None

try:
    from PySide6.QtCore import Qt, QTimer, QThread, QObject, Signal as pyqtSignal
    from PySide6.QtGui import (  # noqa: F401
        QColor, QFont, QIcon, QPixmap, QImage, QPainter, QPalette, QKeySequence,
        QTextCursor, QTextCharFormat, QBrush, QPen, QAction,
    )
    from PySide6.QtWidgets import (  # noqa: F401
        QApplication, QMainWindow, QWidget, QDialog, QDockWidget,
        QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QStackedLayout,
        QLabel, QPushButton, QLineEdit, QTextEdit, QPlainTextEdit,
        QComboBox, QCheckBox, QRadioButton, QSpinBox, QDoubleSpinBox,
        QSlider, QProgressBar, QListWidget, QListWidgetItem,
        QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
        QTabWidget, QTabBar, QGroupBox, QFrame, QScrollArea, QSplitter,
        QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsEllipseItem,
        QGraphicsTextItem, QGraphicsLineItem,
        QMenuBar, QMenu, QToolBar, QStatusBar, QSystemTrayIcon,
        QFileDialog, QMessageBox, QInputDialog, QColorDialog, QFontDialog,
        QSizePolicy, QStyle, QProgressDialog,
    )
    QT_API = "PySide6"
except Exception:
    try:
        from PyQt6.QtCore import Qt, QTimer, QThread, QObject, pyqtSignal
        from PyQt6.QtGui import (  # noqa: F401
            QColor, QFont, QIcon, QPixmap, QImage, QPainter, QPalette, QKeySequence,
            QTextCursor, QTextCharFormat, QBrush, QPen, QAction,
        )
        from PyQt6.QtWidgets import (  # noqa: F401
            QApplication, QMainWindow, QWidget, QDialog, QDockWidget,
            QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QStackedLayout,
            QLabel, QPushButton, QLineEdit, QTextEdit, QPlainTextEdit,
            QComboBox, QCheckBox, QRadioButton, QSpinBox, QDoubleSpinBox,
            QSlider, QProgressBar, QProgressDialog, QListWidget, QListWidgetItem,
            QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
            QTabWidget, QTabBar, QGroupBox, QFrame, QScrollArea, QSplitter,
            QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsEllipseItem,
            QGraphicsTextItem, QGraphicsLineItem,
            QMenuBar, QMenu, QToolBar, QStatusBar, QSystemTrayIcon,
            QFileDialog, QMessageBox, QInputDialog, QColorDialog, QFontDialog,
            QSizePolicy, QStyle,
        )
        QT_API = "PyQt6"
    except Exception:
        try:
            from PyQt5.QtCore import Qt, QTimer, QThread, QObject, pyqtSignal
            from PyQt5.QtGui import (  # noqa: F401
                QColor, QFont, QIcon, QPixmap, QImage, QPainter, QPalette, QKeySequence,
                QTextCursor, QTextCharFormat, QBrush, QPen,
            )
            from PyQt5.QtWidgets import (  # noqa: F401
                QApplication, QMainWindow, QWidget, QDialog, QDockWidget,
                QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QStackedLayout,
                QLabel, QPushButton, QLineEdit, QTextEdit, QPlainTextEdit,
                QComboBox, QCheckBox, QRadioButton, QSpinBox, QDoubleSpinBox,
                QSlider, QProgressBar, QProgressDialog, QListWidget, QListWidgetItem,
                QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
                QTabWidget, QTabBar, QGroupBox, QFrame, QScrollArea, QSplitter,
                QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsEllipseItem,
                QGraphicsTextItem, QGraphicsLineItem,
                QMenuBar, QMenu, QToolBar, QStatusBar, QSystemTrayIcon,
                QFileDialog, QMessageBox, QInputDialog, QColorDialog, QFontDialog,
                QSizePolicy, QAction, QStyle,
            )
            QT_API = "PyQt5"
        except Exception:
            # Headless / test environment: keep stubs subclassable so dock
            # modules can still be imported for audits and tests.
            class _StubMeta(type):
                def __getattr__(cls, name):
                    return cls

            class _Stub(metaclass=_StubMeta):
                def __init__(self, *a, **kw): pass
                def __call__(self, *a, **kw): return self
                def __getattr__(self, name): return self
                def __class_getitem__(cls, item): return cls
                def __or__(self, other): return self
                def __ror__(self, other): return self
            _stub = _Stub()
            Qt = _stub
            QTimer = QThread = QObject = _Stub
            pyqtSignal = pyqtSlot = _stub
            QColor = QFont = QIcon = QPixmap = QImage = QPainter = QPalette = _stub
            QKeySequence = QTextCursor = QTextCharFormat = QBrush = QPen = _stub
            QApplication = QMainWindow = QWidget = QDialog = QDockWidget = _Stub
            QVBoxLayout = QHBoxLayout = QGridLayout = QFormLayout = QStackedLayout = _Stub
            QLabel = QPushButton = QLineEdit = QTextEdit = QPlainTextEdit = _Stub
            QComboBox = QCheckBox = QRadioButton = QSpinBox = QDoubleSpinBox = _Stub
            QSlider = QProgressBar = QProgressDialog = QListWidget = QListWidgetItem = _Stub
            QTreeWidget = QTreeWidgetItem = QTableWidget = QTableWidgetItem = _Stub
            QTabWidget = QTabBar = QGroupBox = QFrame = QScrollArea = QSplitter = _Stub
            QGraphicsView = QGraphicsScene = QGraphicsRectItem = _Stub
            QGraphicsEllipseItem = QGraphicsTextItem = QGraphicsLineItem = _Stub
            QMenuBar = QMenu = QToolBar = QStatusBar = QSystemTrayIcon = _Stub
            QFileDialog = QMessageBox = QInputDialog = QColorDialog = QFontDialog = _Stub
            QSizePolicy = QAction = QStyle = _Stub

__all__ = [k for k in globals().keys() if not k.startswith("_")]
