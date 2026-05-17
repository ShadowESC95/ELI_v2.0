#!/usr/bin/env python3
# eli_pro_audio_gui_MKII.py
"""
ELI Pro Audio GUI MKII - Complete integration with executor_enhanced
Unified control panel for ELI voice assistant with persona lock, memory, and proactive monitoring.
"""
import sys
import os
import time
import threading
import queue
import json
import re
import html
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

# Try to import Qt6, fall back to Qt5
try:
    from PyQt6.QtWidgets import *
    from PyQt6.QtCore import *
    from PyQt6.QtGui import *
    from PyQt6 import QtCore, QtWidgets, QtGui
    QT_VERSION = 6
except ImportError:
    try:
        from PyQt5.QtWidgets import *
        from PyQt5.QtCore import *
        from PyQt5.QtGui import *
        from PyQt5 import QtCore, QtWidgets, QtGui
        QT_VERSION = 5
    except ImportError:
        print("ERROR: PyQt6 or PyQt5 not found. Install with:")
        print("  pip install PyQt6 (recommended) or pip install PyQt5")
        sys.exit(1)

# Add project root to path for imports
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import ELI tools
try:
    # Prefer MKII executor if present (includes streaming hooks); fall back to executor_enhanced.
    try:
        from eli_tools.executor_enhancedMKII import (
        execute, execute_action, chat, chat_stream,
        persona_lock_set, persona_lock_status, persona_lock_clear,
        memory_store, memory_recall,
        get_status, clear_chat_history,
        proactive_start, proactive_stop, proactive_status,
        self_test
    )
    except Exception:
        from eli_tools.executor_enhanced import (
        execute, execute_action, chat,
        persona_lock_set, persona_lock_status, persona_lock_clear,
        memory_store, memory_recall,
        get_status, clear_chat_history,
        proactive_start, proactive_stop, proactive_status,
        self_test
    )
        chat_stream = None
    from eli_tools.capability_registry import list_capabilities, render_detailed
    ELI_AVAILABLE = True
except ImportError as e:
    print(f"WARNING: Could not import ELI tools: {e}")
    ELI_AVAILABLE = False
    # Create dummy functions for GUI to work
    def execute(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}
    execute_action = execute
    def chat(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}
    def persona_lock_set(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}
    def persona_lock_status(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}
    def persona_lock_clear(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}
    def memory_store(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}
    def memory_recall(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}
    def get_status(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}
    def clear_chat_history(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}
    def proactive_start(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}
    def proactive_stop(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}
    def proactive_status(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}
    def self_test(*args, **kwargs):
        return {"ok": False, "error": "ELI tools not available", "content": "ELI tools not available"}

# Try to import voice worker for audio feedback
try:
    from brain.voice_worker import speak as voice_speak
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False
    def voice_speak(text):
        print(f"[TTS] {text}")

# ============================================================================
# CONFIGURATION
# ============================================================================

# Default paths
DEFAULT_STATE_FILE = Path.home() / ".eli_state.json"
DEFAULT_MEMORY_FILE = Path.home() / ".eli_memory.jsonl"

# UI Colors (dark theme)
COLORS = {
    "bg_dark": "#1e1e1e",
    "bg_panel": "#252526",
    "bg_widget": "#2d2d30",
    "text_primary": "#ffffff",
    "text_secondary": "#cccccc",
    "text_muted": "#888888",
    "accent_blue": "#007acc",
    "accent_green": "#4ec9b0",
    "accent_orange": "#ce9178",
    "accent_red": "#f44747",
    "border": "#3e3e42",
    "success": "#4caf50",
    "warning": "#ff9800",
    "error": "#f44336",
}

# Fonts
FONT_FAMILY = "Segoe UI, Ubuntu, Cantarell, sans-serif"
FONT_MONO = "Consolas, 'Courier New', monospace"

# ============================================================================
# CUSTOM WIDGETS
# ============================================================================

class StatusLED(QWidget):
    """Custom LED indicator widget."""
    def __init__(self, size=12, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._color = QColor(COLORS["text_muted"])
        self._blinking = False
        self._blink_state = False
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._toggle_blink)
        
    def set_color(self, color):
        """Set LED color (QColor or hex string)."""
        if isinstance(color, str):
            self._color = QColor(color)
        else:
            self._color = color
        self.update()
        
    def set_blinking(self, blink, interval=500):
        """Enable/disable blinking."""
        self._blinking = blink
        if blink:
            self._blink_timer.start(interval)
        else:
            self._blink_timer.stop()
            self._blink_state = False
        self.update()
        
    def _toggle_blink(self):
        """Toggle blink state."""
        self._blink_state = not self._blink_state
        self.update()
        
    def paintEvent(self, event):
        """Paint the LED."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Background circle
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLORS["bg_widget"]))
        painter.drawEllipse(0, 0, self.width(), self.height())
        
        # LED circle
        if self._blinking and not self._blink_state:
            color = QColor(self._color)
            color.setAlpha(100)
        else:
            color = self._color
            
        painter.setBrush(color)
        painter.drawEllipse(1, 1, self.width()-2, self.height()-2)
        
        # Highlight
        highlight = QRadialGradient(self.width()/3, self.height()/3, self.width()/2)
        highlight.setColorAt(0, QColor(255, 255, 255, 100))
        highlight.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(highlight))
        painter.drawEllipse(2, 2, self.width()-4, self.height()-4)

class ToggleSwitch(QWidget):
    """Custom toggle switch widget."""
    
    # Define the signal FIRST
    toggled = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(52, 24)
        self._checked = False
        self._pos = 4  # Initialize _pos attribute
        
        # Create animation - must use bytes for property name
        self._animation = QPropertyAnimation(self, b"pos_value")
        self._animation.setDuration(150)
        
    def is_checked(self):
        return self._checked
        
    def set_checked(self, checked):
        if self._checked != checked:
            self._checked = checked
            target_pos = 28 if checked else 4
            self._animation.setEndValue(target_pos)
            self._animation.start()
            self.toggled.emit(checked)  # Now toggled signal exists
            
    def mousePressEvent(self, event):
        self.set_checked(not self._checked)
        
    def get_pos_value(self):
        return self._pos
        
    def set_pos_value(self, pos):
        self._pos = pos
        self.update()
        
    # Define the property
    pos_value = pyqtProperty(int, get_pos_value, set_pos_value)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Background
        bg_color = QColor(COLORS["accent_blue"] if self._checked else COLORS["bg_widget"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_color)
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 12, 12)
        
        # Slider
        slider_color = QColor(COLORS["text_primary"])
        painter.setBrush(slider_color)
        painter.drawEllipse(self._pos, 4, 16, 16)

class CommandButton(QPushButton):
    """Styled command button for actions."""
    def __init__(self, text, icon=None, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: 500;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_blue']}20;
                border-color: {COLORS['accent_blue']};
            }}
            QPushButton:pressed {{
                background-color: {COLORS['accent_blue']}40;
            }}
        """)
        if icon:
            self.setIcon(icon)

class ChatStreamWorker(QObject):
    """Background worker that streams tokens from chat_stream (or falls back to chat())."""

    token = pyqtSignal(str)
    done = pyqtSignal(dict)

    def __init__(self, message: str, parent=None):
        super().__init__(parent)
        self.message = message
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    @pyqtSlot()
    def run(self):
        try:
            # Try to use streaming if available
            if "chat_stream" in globals() and chat_stream is not None:
                buf = []
                for tok in chat_stream(self.message):
                    if self._stop_flag:
                        self.done.emit({"ok": False, "error": "stream_cancelled", "content": "(cancelled)"})
                        return
                    if tok:
                        buf.append(tok)
                        self.token.emit(tok)

                content = "".join(buf)
                self.done.emit({"ok": True, "content": content, "response": content})
            else:
                # Fallback to regular chat if streaming not available
                res = chat(self.message)
                if isinstance(res, dict):
                    content = res.get("content", "") or res.get("response", "")
                    # Emit as a single token if no streaming
                    if content:
                        self.token.emit(content)
                    self.done.emit(res)
                else:
                    self.done.emit({"ok": False, "error": "bad_result", "content": str(res)})
        except Exception as e:
            self.done.emit({"ok": False, "error": str(e), "content": f"Error: {e}"})

# ============================================================================
# MAIN GUI
# ============================================================================


# =============================================================================
# OPEN_APP autocomplete helpers (GUI)
# =============================================================================

def fetch_open_app_names(execute_fn, refresh: bool = False) -> List[str]:
    """
    Pull the app catalog from the executor (OPEN_APP_LIST). Returns a list of names.
    Falls back to [] if executor doesn't support it yet.
    """
    try:
        r = execute_fn("OPEN_APP_LIST", {"refresh": bool(refresh)})
        if isinstance(r, dict) and r.get("ok") and isinstance(r.get("names"), list):
            # de-dupe, stable order
            seen = set()
            out = []
            for n in r["names"]:
                if not isinstance(n, str):
                    continue
                k = n.strip()
                if not k:
                    continue
                kl = k.lower()
                if kl in seen:
                    continue
                seen.add(kl)
                out.append(k)
            return out
    except Exception:
        pass
    return []

class EliOpenAppCompleter(QtCore.QObject):
    """
    QTextEdit completer for "open <app>".
    Trigger: typing 'open ' (or 'open app ') then showing an app-name dropdown.
    """
    def __init__(self, text_edit: QtWidgets.QTextEdit, get_items_fn, parent=None):
        super().__init__(parent)
        self.text_edit = text_edit
        self.get_items_fn = get_items_fn

        self._model = QtCore.QStringListModel([])
        self.completer = QtWidgets.QCompleter(self._model, self.text_edit)

        # PyQt5: Qt.CaseInsensitive exists
        # PyQt6: enum moved to Qt.CaseSensitivity.CaseInsensitive
        self.completer.setCaseSensitivity(
            getattr(QtCore.Qt, "CaseInsensitive", QtCore.Qt.CaseSensitivity.CaseInsensitive)
        )

        # PyQt5: Qt.MatchStartsWith exists
        # PyQt6: enum moved to Qt.MatchFlag.MatchStartsWith
        self.completer.setFilterMode(
            getattr(QtCore.Qt, "MatchStartsWith", QtCore.Qt.MatchFlag.MatchStartsWith)
        )

        # PyQt5: QCompleter.PopupCompletion exists
        # PyQt6: enum moved to QCompleter.CompletionMode.PopupCompletion
        self.completer.setCompletionMode(
            getattr(QtWidgets.QCompleter, "PopupCompletion",
                    QtWidgets.QCompleter.CompletionMode.PopupCompletion)
        )

        self.completer.activated.connect(self._insert_completion)
        self.text_edit.installEventFilter(self)

        self._active = False
        self._typed = ""
        self._trigger_start_pos = None


    def refresh(self):
        items = []
        try:
            items = list(self.get_items_fn() or [])
        except Exception:
            items = []
        self._model.setStringList(items)

    def _line_text_before_cursor(self) -> str:
        tc = self.text_edit.textCursor()
        block = tc.block()
        line = block.text()
        pos_in_block = tc.position() - block.position()
        return line[:max(0, pos_in_block)]

    def _find_open_prefix(self, s: str):
        """
        Returns (trigger, typed) or (None, None).
        Accepts 'open ' and 'open app '.
        """
        sl = s.lower()
        for trig in ("open app ", "open "):
            j = sl.rfind(trig)
            if j >= 0:
                # ensure word boundary-ish
                if j == 0 or sl[j-1].isspace():
                    typed = s[j+len(trig):]
                    return trig, typed
        return None, None

    def eventFilter(self, obj, ev):
        if obj is not self.text_edit:
            return False

        try:
            # PyQt5: QtCore.QEvent.KeyPress
            # PyQt6: QtCore.QEvent.Type.KeyPress
            KEY_PRESS = getattr(QtCore.QEvent, 'KeyPress', getattr(getattr(QtCore.QEvent, 'Type', None), 'KeyPress', None))
            if KEY_PRESS is None or ev.type() != KEY_PRESS:
                return False

            key = ev.key()
            mod = ev.modifiers()

            # PyQt5: QtCore.Qt.ControlModifier
            # PyQt6: QtCore.Qt.KeyboardModifier.ControlModifier
            CTRL_MOD = getattr(QtCore.Qt, 'ControlModifier', QtCore.Qt.KeyboardModifier.ControlModifier)

            # PyQt5: QtCore.Qt.Key_*
            # PyQt6: QtCore.Qt.Key.Key_*
            QtKey = getattr(QtCore.Qt, 'Key', QtCore.Qt)

            if self.completer.popup().isVisible():
                if key in (
                    getattr(QtKey, 'Key_Enter', None),
                    getattr(QtKey, 'Key_Return', None),
                    getattr(QtKey, 'Key_Escape', None),
                    getattr(QtKey, 'Key_Up', None),
                    getattr(QtKey, 'Key_Down', None),
                    getattr(QtKey, 'Key_Tab', None),
                ):
                    return False

            force = bool(mod & CTRL_MOD) and (key == getattr(QtKey, 'Key_Space', None))

            before = self._line_text_before_cursor()
            trig, typed = self._find_open_prefix(before)

            if (not force) and (trig is None):
                self._active = False
                return False

            # Refresh model lazily
            self.refresh()

            if trig is None:
                trig = 'open '
                typed = ''

            self._typed = typed or ''
            self._active = True

            self.completer.setCompletionPrefix(self._typed)
            popup = self.completer.popup()

            # Position popup at cursor
            cr = self.text_edit.cursorRect()
            try:
                cr.setWidth(popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width())
            except Exception:
                pass
            self.completer.complete(cr)
            return False

        except Exception:
            # Never crash the entire GUI from an event filter.
            return False

    def _insert_completion(self, completion: str):
        if not self._active:
            return
        tc = self.text_edit.textCursor()
        # Insert only the missing suffix beyond what user typed
        typed = self._typed or ""
        if completion.lower().startswith(typed.lower()):
            suffix = completion[len(typed):]
        else:
            suffix = completion
        tc.insertText(suffix)
        self.text_edit.setTextCursor(tc)
        self._active = False


class EliProAudioGUI(QMainWindow):
    """Main ELI Pro Audio GUI window."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ELI Pro Audio Control MKII")
        self.setGeometry(100, 100, 1200, 800)
        
        # Initialize state
        self._status_check_timer = QTimer(self)
        self._status_check_timer.timeout.connect(self._check_system_status)
        self._status_check_timer.start(5000)  # Check every 5 seconds
        
        self._proactive_check_timer = QTimer(self)
        self._proactive_check_timer.timeout.connect(self._update_proactive_status)
        self._proactive_check_timer.start(10000)  # Check every 10 seconds
        
        self._chat_history = []
        self._system_status = {}
        self._persona_lock_status = {}
        self._proactive_status = {}
        self._voice_enabled = True  # Default to enabled
        # Chat rendering model (keeps HTML stable while allowing streaming updates)
        self._chat_items = []  # list of dict(role, ts, content)
        self._streaming_index = None
        self._stream_thread = None
        self._stream_worker = None
        self._stream_qthread = None
        self._render_pending = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_chat)

        
        # Setup UI
        self._setup_ui()
        self._load_state()

        # Live clock
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()

        # Hotkeys
        self._install_hotkeys()
        
        # Initial status check
        self._check_system_status()
        
    def _setup_ui(self):
        """Setup the main UI."""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Left sidebar (navigation)
        sidebar = self._create_sidebar()
        main_layout.addWidget(sidebar)
        
        # Main content area
        content_stack = QStackedWidget()
        content_stack.setStyleSheet(f"background-color: {COLORS['bg_panel']};")
        
        # Add content pages
        self._dashboard_page = self._create_dashboard_page()
        self._chat_page = self._create_chat_page()
        self._persona_page = self._create_persona_page()
        self._memory_page = self._create_memory_page()
        self._proactive_page = self._create_proactive_page()
        self._settings_page = self._create_settings_page()
        
        content_stack.addWidget(self._dashboard_page)
        content_stack.addWidget(self._chat_page)
        content_stack.addWidget(self._persona_page)
        content_stack.addWidget(self._memory_page)
        content_stack.addWidget(self._proactive_page)
        content_stack.addWidget(self._settings_page)
        
        main_layout.addWidget(content_stack, 1)
        
        # Connect sidebar to content stack
        self._sidebar_list.currentRowChanged.connect(content_stack.setCurrentIndex)
        
    def _create_sidebar(self):
        """Create the left sidebar."""
        sidebar = QWidget()
        sidebar.setFixedWidth(220)
        sidebar.setStyleSheet(f"""
            background-color: {COLORS['bg_dark']};
            border-right: 1px solid {COLORS['border']};
        """)
        
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        
        # Logo/title
        title_label = QLabel("ELI Pro Audio")
        title_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {COLORS['accent_blue']};
            padding-bottom: 16px;
            border-bottom: 1px solid {COLORS['border']};
        """)
        layout.addWidget(title_label)
        
        # Navigation list
        self._sidebar_list = QListWidget()
        self._sidebar_list.setStyleSheet(f"""
            QListWidget {{
                background-color: transparent;
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                color: {COLORS['text_secondary']};
                padding: 10px 12px;
                border-radius: 4px;
                margin: 2px 0;
            }}
            QListWidget::item:hover {{
                background-color: {COLORS['bg_widget']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['accent_blue']};
                color: white;
            }}
        """)
        self._sidebar_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        # Add navigation items
        nav_items = [
            ("Dashboard", "📊"),
            ("Chat", "💬"),
            ("Persona Lock", "🔒"),
            ("Memory", "🧠"),
            ("Proactive", "⚡"),
            ("Settings", "⚙️"),
        ]
        
        for text, icon in nav_items:
            item = QListWidgetItem(f"{icon}  {text}")
            item.setSizeHint(QSize(0, 40))
            self._sidebar_list.addItem(item)
        
        layout.addWidget(self._sidebar_list)
        layout.addStretch()
        
        # Status bar at bottom
        status_widget = QWidget()
        status_widget.setStyleSheet(f"""
            background-color: {COLORS['bg_widget']};
            border-radius: 6px;
            padding: 8px;
        """)
        status_layout = QVBoxLayout(status_widget)
        status_layout.setContentsMargins(8, 8, 8, 8)
        
        # Status indicators
        self._status_led = StatusLED(10)
        self._status_label = QLabel("Checking...")
        self._status_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        
        status_row = QHBoxLayout()
        status_row.addWidget(self._status_led)
        status_row.addWidget(self._status_label, 1)
        status_layout.addLayout(status_row)

        # UI state + clock
        self._ui_state_label = QLabel("IDLE")
        self._ui_state_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        status_layout.addWidget(self._ui_state_label)

        self._clock_label = QLabel("--:--:--")
        self._clock_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        status_layout.addWidget(self._clock_label)
        
        layout.addWidget(status_widget)
        
        return sidebar
        
    def _create_dashboard_page(self):
        """Create the dashboard page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Header
        header = QLabel("Dashboard")
        header.setStyleSheet(f"""
            font-size: 24px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            padding-bottom: 8px;
            border-bottom: 1px solid {COLORS['border']};
        """)
        layout.addWidget(header)
        
        # Stats grid
        stats_grid = QGridLayout()
        stats_grid.setSpacing(12)
        
        # System status card
        sys_card = self._create_stat_card("System Status", "📊", "Checking...")
        self._sys_status_label = sys_card.findChild(QLabel, "value")
        stats_grid.addWidget(sys_card, 0, 0)
        
        # Persona lock card
        persona_card = self._create_stat_card("Persona Lock", "🔒", "Checking...")
        self._persona_status_label = persona_card.findChild(QLabel, "value")
        stats_grid.addWidget(persona_card, 0, 1)
        
        # Memory card
        memory_card = self._create_stat_card("Memory", "🧠", "Checking...")
        self._memory_status_label = memory_card.findChild(QLabel, "value")
        stats_grid.addWidget(memory_card, 1, 0)
        
        # Proactive card
        proactive_card = self._create_stat_card("Proactive", "⚡", "Checking...")
        self._proactive_status_label = proactive_card.findChild(QLabel, "value")
        stats_grid.addWidget(proactive_card, 1, 1)
        
        layout.addLayout(stats_grid)
        
        # Quick actions
        actions_label = QLabel("Quick Actions")
        actions_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            margin-top: 8px;
        """)
        layout.addWidget(actions_label)
        
        actions_grid = QGridLayout()
        actions_grid.setSpacing(8)
        
        # Row 1
        actions_grid.addWidget(self._create_action_button("Test Chat", self._test_chat), 0, 0)
        actions_grid.addWidget(self._create_action_button("Check Lock", self._check_persona_lock), 0, 1)
        actions_grid.addWidget(self._create_action_button("Memory Recall", self._quick_memory_recall), 0, 2)
        
        # Row 2
        actions_grid.addWidget(self._create_action_button("Self Test", self._run_self_test), 1, 0)
        actions_grid.addWidget(self._create_action_button("Clear History", self._clear_chat_history), 1, 1)
        actions_grid.addWidget(self._create_action_button("Voice Test", self._test_voice), 1, 2)
        
        layout.addLayout(actions_grid)
        
        # Recent activity
        activity_label = QLabel("Recent Activity")
        activity_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            margin-top: 8px;
        """)
        layout.addWidget(activity_label)
        
        self._activity_log = QTextEdit()
        self._activity_log.setReadOnly(True)
        self._activity_log.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-family: {FONT_MONO};
                font-size: 12px;
            }}
        """)
        self._activity_log.setMaximumHeight(120)
        layout.addWidget(self._activity_log)
        
        layout.addStretch()
        
        return page
        
    def _create_chat_page(self):
        """Create the chat page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Header
        header = QLabel("Chat with ELI")
        header.setStyleSheet(f"""
            font-size: 24px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            padding-bottom: 8px;
            border-bottom: 1px solid {COLORS['border']};
        """)
        layout.addWidget(header)
        
        # Chat history
        self._chat_display = QTextEdit()
        self._chat_display.setReadOnly(True)
        self._chat_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
                line-height: 1.4;
            }}
        """)
        layout.addWidget(self._chat_display, 1)
        
        # Input area
        input_widget = QWidget()
        input_layout = QHBoxLayout(input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)
        
        self._chat_input = QTextEdit()
        self._chat_input.setPlaceholderText("Type your message here...")
        # OPEN_APP autocomplete: pull app names from executor and attach completer.
        try:
            self._open_app_names = fetch_open_app_names(execute, refresh=False)
        except Exception:
            self._open_app_names = []
        self._open_app_completer = EliOpenAppCompleter(self._chat_input, lambda: self._open_app_names)
        
        self._chat_input.setMaximumHeight(80)
        self._chat_input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 8px;
                font-size: 14px;
            }}
            QTextEdit:focus {{
                border-color: {COLORS['accent_blue']};
            }}
        """)
        input_layout.addWidget(self._chat_input, 1)
        
        # Send button
        send_btn = QPushButton("Send")
        self._chat_send_btn = send_btn
        send_btn.setFixedWidth(80)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_blue']}dd;
            }}
            QPushButton:pressed {{
                background-color: {COLORS['accent_blue']}bb;
            }}
            QPushButton:disabled {{
                background-color: {COLORS['border']};
                color: {COLORS['text_muted']};
            }}
        """)
        send_btn.clicked.connect(self._send_chat_message)
        input_layout.addWidget(send_btn)
        
        layout.addWidget(input_widget)
        
        # Control buttons
        control_widget = QWidget()
        control_layout = QHBoxLayout(control_widget)
        control_layout.setContentsMargins(0, 0, 0, 0)
        
        clear_btn = QPushButton("Clear Chat")
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_red']}20;
                border-color: {COLORS['accent_red']};
            }}
        """)
        clear_btn.clicked.connect(self._clear_chat_display)
        control_layout.addWidget(clear_btn)

        # Voice control (STT) placeholders - wire to your voice daemon later
        self._voice_start_btn = QPushButton("🎙 Start Listen")
        self._voice_stop_btn = QPushButton("⏹ Stop Listen")
        for b in (self._voice_start_btn, self._voice_stop_btn):
            b.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_widget']};
                    color: {COLORS['text_primary']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 4px;
                    padding: 8px 12px;
                    margin-left: 8px;
                }}
                QPushButton:hover {{
                    background-color: {COLORS['accent_blue']}20;
                    border-color: {COLORS['accent_blue']};
                }}
            """)
        self._voice_start_btn.clicked.connect(self._voice_listen_start)
        self._voice_stop_btn.clicked.connect(self._voice_listen_stop)
        control_layout.addWidget(self._voice_start_btn)
        control_layout.addWidget(self._voice_stop_btn)

        control_layout.addStretch()
        
        voice_toggle = ToggleSwitch()
        voice_toggle.set_checked(True)
        voice_toggle.toggled.connect(self._toggle_voice_feedback)
        voice_label = QLabel("Voice Feedback")
        voice_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        
        voice_row = QHBoxLayout()
        voice_row.addWidget(voice_label)
        voice_row.addWidget(voice_toggle)
        voice_row.addStretch()
        control_layout.addLayout(voice_row)
        
        layout.addWidget(control_widget)
        
        return page
        
    def _create_persona_page(self):
        """Create the persona lock page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Header
        header = QLabel("Persona Lock Management")
        header.setStyleSheet(f"""
            font-size: 24px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            padding-bottom: 8px;
            border-bottom: 1px solid {COLORS['border']};
        """)
        layout.addWidget(header)
        
        # Status display
        status_card = QWidget()
        status_card.setStyleSheet(f"""
            background-color: {COLORS['bg_widget']};
            border: 1px solid {COLORS['border']};
            border-radius: 8px;
            padding: 16px;
        """)
        status_layout = QVBoxLayout(status_card)
        
        self._persona_status_display = QLabel("Checking persona lock status...")
        self._persona_status_display.setStyleSheet(f"""
            color: {COLORS['text_secondary']};
            font-size: 14px;
            line-height: 1.4;
        """)
        self._persona_status_display.setWordWrap(True)
        status_layout.addWidget(self._persona_status_display)
        
        layout.addWidget(status_card)
        
        # Lock controls
        controls_label = QLabel("Lock Controls")
        controls_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            margin-top: 8px;
        """)
        layout.addWidget(controls_label)
        
        controls_grid = QGridLayout()
        controls_grid.setSpacing(8)
        
        # Model selection
        model_label = QLabel("Model:")
        model_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        controls_grid.addWidget(model_label, 0, 0)
        
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px;
                min-width: 200px;
            }}
            QComboBox:focus {{
                border-color: {COLORS['accent_blue']};
            }}
        """)
        # Populate with common models
        self._model_combo.addItems([
            "eli-persona:latest",
            "qwen2.5:7b",
            "llama3.2:3b",
            "mistral:7b",
            "phi3:mini"
        ])
        controls_grid.addWidget(self._model_combo, 0, 1)

        refresh_models_btn = QPushButton("Refresh Models")
        refresh_models_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_blue']}20;
                border-color: {COLORS['accent_blue']};
            }}
        """)
        refresh_models_btn.clicked.connect(self._refresh_models)
        controls_grid.addWidget(refresh_models_btn, 0, 2)
        
        # Modelfile path
        modelfile_label = QLabel("Modelfile:")
        modelfile_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        controls_grid.addWidget(modelfile_label, 1, 0)
        
        modelfile_widget = QWidget()
        modelfile_layout = QHBoxLayout(modelfile_widget)
        modelfile_layout.setContentsMargins(0, 0, 0, 0)
        
        self._modelfile_edit = QLineEdit()
        self._modelfile_edit.setPlaceholderText("Path to Modelfile (optional)")
        self._modelfile_edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px;
            }}
            QLineEdit:focus {{
                border-color: {COLORS['accent_blue']};
            }}
        """)
        modelfile_layout.addWidget(self._modelfile_edit, 1)
        
        browse_btn = QPushButton("Browse")
        browse_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_blue']}20;
                border-color: {COLORS['accent_blue']};
            }}
        """)
        browse_btn.clicked.connect(self._browse_modelfile)
        modelfile_layout.addWidget(browse_btn)
        
        controls_grid.addWidget(modelfile_widget, 1, 1)
        
        layout.addLayout(controls_grid)
        
        # Action buttons
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)
        
        set_lock_btn = QPushButton("Set Lock")
        set_lock_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_green']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_green']}dd;
            }}
        """)
        set_lock_btn.clicked.connect(self._set_persona_lock)
        action_layout.addWidget(set_lock_btn)
        
        check_lock_btn = QPushButton("Check Lock")
        check_lock_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_blue']}dd;
            }}
        """)
        check_lock_btn.clicked.connect(self._check_persona_lock)
        action_layout.addWidget(check_lock_btn)
        
        clear_lock_btn = QPushButton("Clear Lock")
        clear_lock_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_red']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_red']}dd;
            }}
        """)
        clear_lock_btn.clicked.connect(self._clear_persona_lock)
        action_layout.addWidget(clear_lock_btn)
        
        action_layout.addStretch()
        
        layout.addWidget(action_widget)
        
        # Lock details
        details_label = QLabel("Lock Details")
        details_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            margin-top: 8px;
        """)
        layout.addWidget(details_label)
        
        self._lock_details = QTextEdit()
        self._lock_details.setReadOnly(True)
        self._lock_details.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-family: {FONT_MONO};
                font-size: 12px;
            }}
        """)
        self._lock_details.setMaximumHeight(200)
        layout.addWidget(self._lock_details)
        
        layout.addStretch()
        
        return page
        
    def _create_memory_page(self):
        """Create the memory page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Header
        header = QLabel("Memory Management")
        header.setStyleSheet(f"""
            font-size: 24px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            padding-bottom: 8px;
            border-bottom: 1px solid {COLORS['border']};
        """)
        layout.addWidget(header)
        
        # Store memory
        store_label = QLabel("Store Memory")
        store_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {COLORS['text_primary']};
        """)
        layout.addWidget(store_label)
        
        store_widget = QWidget()
        store_layout = QVBoxLayout(store_widget)
        store_layout.setContentsMargins(0, 0, 0, 0)
        
        self._memory_input = QTextEdit()
        self._memory_input.setPlaceholderText("Enter text to store in memory...")
        self._memory_input.setMaximumHeight(80)
        self._memory_input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 8px;
                font-size: 14px;
            }}
        """)
        store_layout.addWidget(self._memory_input)
        
        tags_widget = QWidget()
        tags_layout = QHBoxLayout(tags_widget)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        
        tags_label = QLabel("Tags (comma-separated):")
        tags_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        tags_layout.addWidget(tags_label)
        
        self._memory_tags = QLineEdit()
        self._memory_tags.setPlaceholderText("tag1, tag2, tag3")
        self._memory_tags.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px;
            }}
        """)
        tags_layout.addWidget(self._memory_tags, 1)
        store_layout.addWidget(tags_widget)
        
        store_btn = QPushButton("Store Memory")
        store_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_green']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_green']}dd;
            }}
        """)
        store_btn.clicked.connect(self._store_memory)
        store_layout.addWidget(store_btn)
        
        layout.addWidget(store_widget)
        
        # Recall memory
        recall_label = QLabel("Recall Memory")
        recall_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            margin-top: 16px;
        """)
        layout.addWidget(recall_label)
        
        recall_widget = QWidget()
        recall_layout = QHBoxLayout(recall_widget)
        recall_layout.setContentsMargins(0, 0, 0, 0)
        
        self._memory_query = QLineEdit()
        self._memory_query.setPlaceholderText("Search query...")
        self._memory_query.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px;
            }}
        """)
        recall_layout.addWidget(self._memory_query, 1)
        
        limit_label = QLabel("Limit:")
        limit_label.setStyleSheet(f"color: {COLORS['text_secondary']}; padding: 0 8px;")
        recall_layout.addWidget(limit_label)
        
        self._memory_limit = QSpinBox()
        self._memory_limit.setRange(1, 50)
        self._memory_limit.setValue(10)
        self._memory_limit.setStyleSheet(f"""
            QSpinBox {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px;
            }}
        """)
        recall_layout.addWidget(self._memory_limit)
        
        recall_btn = QPushButton("Recall")
        recall_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
                margin-left: 8px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_blue']}dd;
            }}
        """)
        recall_btn.clicked.connect(self._recall_memory)
        recall_layout.addWidget(recall_btn)
        
        layout.addWidget(recall_widget)
        
        # Memory results
        self._memory_results = QTextEdit()
        self._memory_results.setReadOnly(True)
        self._memory_results.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-family: {FONT_MONO};
                font-size: 12px;
            }}
        """)
        layout.addWidget(self._memory_results, 1)
        
        return page
        
    def _create_proactive_page(self):
        """Create the proactive monitoring page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Header
        header = QLabel("Proactive Monitoring")
        header.setStyleSheet(f"""
            font-size: 24px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            padding-bottom: 8px;
            border-bottom: 1px solid {COLORS['border']};
        """)
        layout.addWidget(header)
        
        # Status card
        status_card = QWidget()
        status_card.setStyleSheet(f"""
            background-color: {COLORS['bg_widget']};
            border: 1px solid {COLORS['border']};
            border-radius: 8px;
            padding: 16px;
        """)
        status_layout = QVBoxLayout(status_card)
        
        self._proactive_status_display = QLabel("Checking proactive daemon status...")
        self._proactive_status_display.setStyleSheet(f"""
            color: {COLORS['text_secondary']};
            font-size: 14px;
            line-height: 1.4;
        """)
        self._proactive_status_display.setWordWrap(True)
        status_layout.addWidget(self._proactive_status_display)
        
        layout.addWidget(status_card)
        
        # Controls
        controls_label = QLabel("Daemon Controls")
        controls_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            margin-top: 8px;
        """)
        layout.addWidget(controls_label)
        
        controls_widget = QWidget()
        controls_layout = QHBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        
        start_btn = QPushButton("Start Proactive")
        start_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_green']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_green']}dd;
            }}
        """)
        start_btn.clicked.connect(self._start_proactive)
        controls_layout.addWidget(start_btn)
        
        stop_btn = QPushButton("Stop Proactive")
        stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_red']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_red']}dd;
            }}
        """)
        stop_btn.clicked.connect(self._stop_proactive)
        controls_layout.addWidget(stop_btn)
        
        refresh_btn = QPushButton("Refresh Status")
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_blue']}dd;
            }}
        """)
        refresh_btn.clicked.connect(self._update_proactive_status)
        controls_layout.addWidget(refresh_btn)
        
        controls_layout.addStretch()
        
        layout.addWidget(controls_widget)
        
        # Log display
        log_label = QLabel("Daemon Log (last 1000 lines)")
        log_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            margin-top: 8px;
        """)
        layout.addWidget(log_label)
        
        self._proactive_log = QTextEdit()
        self._proactive_log.setReadOnly(True)
        self._proactive_log.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 8px;
                font-family: {FONT_MONO};
                font-size: 11px;
            }}
        """)
        layout.addWidget(self._proactive_log, 1)
        
        # Log controls
        log_controls = QWidget()
        log_controls_layout = QHBoxLayout(log_controls)
        log_controls_layout.setContentsMargins(0, 0, 0, 0)
        
        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_red']}20;
                border-color: {COLORS['accent_red']};
            }}
        """)
        clear_log_btn.clicked.connect(self._clear_proactive_log)
        log_controls_layout.addWidget(clear_log_btn)
        
        refresh_log_btn = QPushButton("Refresh Log")
        refresh_log_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_widget']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border']};
                border-radius: 4px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_blue']}20;
                border-color: {COLORS['accent_blue']};
            }}
        """)
        refresh_log_btn.clicked.connect(self._refresh_proactive_log)
        log_controls_layout.addWidget(refresh_log_btn)
        
        log_controls_layout.addStretch()
        
        auto_refresh = ToggleSwitch()
        auto_refresh.set_checked(True)
        auto_refresh.toggled.connect(self._toggle_auto_refresh)
        auto_label = QLabel("Auto-refresh (10s)")
        auto_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        
        auto_row = QHBoxLayout()
        auto_row.addWidget(auto_label)
        auto_row.addWidget(auto_refresh)
        auto_row.addStretch()
        log_controls_layout.addLayout(auto_row)
        
        layout.addWidget(log_controls)
        
        return page
        
    def _create_settings_page(self):
        """Create the settings page."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Header
        header = QLabel("Settings")
        header.setStyleSheet(f"""
            font-size: 24px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            padding-bottom: 8px;
            border-bottom: 1px solid {COLORS['border']};
        """)
        layout.addWidget(header)
        
        # ELI Configuration
        eli_label = QLabel("ELI Configuration")
        eli_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {COLORS['text_primary']};
        """)
        layout.addWidget(eli_label)
        
        config_widget = QWidget()
        config_layout = QFormLayout(config_widget)
        config_layout.setSpacing(8)
        
        # Model settings
        self._settings_model = QLineEdit(os.environ.get("ELI_CHAT_MODEL", ""))
        self._settings_model.setPlaceholderText("e.g., eli-persona:latest")
        config_layout.addRow("Chat Model:", self._settings_model)
        
        self._settings_router_model = QLineEdit(os.environ.get("ELI_ROUTER_MODEL", ""))
        self._settings_router_model.setPlaceholderText("e.g., eli-router:latest")
        config_layout.addRow("Router Model:", self._settings_router_model)
        
        self._settings_ollama_host = QLineEdit(os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
        config_layout.addRow("Ollama Host:", self._settings_ollama_host)
        
        layout.addWidget(config_widget)
        
        # Path settings
        path_label = QLabel("Path Configuration")
        path_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            margin-top: 16px;
        """)
        layout.addWidget(path_label)
        
        path_widget = QWidget()
        path_layout = QFormLayout(path_widget)
        path_layout.setSpacing(8)
        
        self._settings_state_file = QLineEdit(str(DEFAULT_STATE_FILE))
        browse_state_btn = QPushButton("Browse")
        browse_state_btn.clicked.connect(lambda: self._browse_file(self._settings_state_file))
        path_layout.addRow("State File:", self._create_browse_row(self._settings_state_file, browse_state_btn))
        
        self._settings_memory_file = QLineEdit(str(DEFAULT_MEMORY_FILE))
        browse_memory_btn = QPushButton("Browse")
        browse_memory_btn.clicked.connect(lambda: self._browse_file(self._settings_memory_file))
        path_layout.addRow("Memory File:", self._create_browse_row(self._settings_memory_file, browse_memory_btn))
        
        layout.addWidget(path_widget)
        
        # Behavior settings
        behavior_label = QLabel("Behavior Settings")
        behavior_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            margin-top: 16px;
        """)
        layout.addWidget(behavior_label)
        
        behavior_widget = QWidget()
        behavior_layout = QFormLayout(behavior_widget)
        behavior_layout.setSpacing(8)
        
        self._settings_lock_enforced = QCheckBox()
        self._settings_lock_enforced.setChecked(os.environ.get("ELI_LOCK_ENFORCED", "1") != "0")
        behavior_layout.addRow("Enforce Persona Lock:", self._settings_lock_enforced)
        
        self._settings_max_history = QSpinBox()
        self._settings_max_history.setRange(1, 1000)
        self._settings_max_history.setValue(int(os.environ.get("ELI_MAX_HISTORY_MESSAGES", "32")))
        behavior_layout.addRow("Max Chat History:", self._settings_max_history)
        
        self._settings_temperature = QDoubleSpinBox()
        self._settings_temperature.setRange(0.0, 2.0)
        self._settings_temperature.setSingleStep(0.1)
        self._settings_temperature.setValue(float(os.environ.get("ELI_TEMPERATURE", "0.7")))
        behavior_layout.addRow("Temperature:", self._settings_temperature)
        
        layout.addWidget(behavior_widget)
        
        # Save/Reset buttons
        button_widget = QWidget()
        button_layout = QHBoxLayout(button_widget)
        button_layout.setContentsMargins(0, 0, 0, 0)
        
        save_btn = QPushButton("Save Settings")
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_green']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_green']}dd;
            }}
        """)
        save_btn.clicked.connect(self._save_settings)
        button_layout.addWidget(save_btn)
        
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_red']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_red']}dd;
            }}
        """)
        reset_btn.clicked.connect(self._reset_settings)
        button_layout.addWidget(reset_btn)
        
        reload_btn = QPushButton("Reload from Environment")
        reload_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_blue']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_blue']}dd;
            }}
        """)
        reload_btn.clicked.connect(self._reload_settings)
        button_layout.addWidget(reload_btn)
        
        button_layout.addStretch()
        
        layout.addWidget(button_widget)
        
        layout.addStretch()
        
        return page
        
    # ============================================================================
    # UI HELPER METHODS
    # ============================================================================
    
    def _create_stat_card(self, title, icon, value_text):
        """Create a statistics card."""
        card = QWidget()
        card.setStyleSheet(f"""
            background-color: {COLORS['bg_widget']};
            border: 1px solid {COLORS['border']};
            border-radius: 8px;
            padding: 16px;
        """)
        layout = QVBoxLayout(card)
        
        # Title row
        title_row = QHBoxLayout()
        title_label = QLabel(f"{icon}  {title}")
        title_label.setStyleSheet(f"""
            font-size: 14px;
            font-weight: bold;
            color: {COLORS['text_secondary']};
        """)
        title_row.addWidget(title_label)
        title_row.addStretch()
        layout.addLayout(title_row)
        
        # Value
        value_label = QLabel(value_text)
        value_label.setObjectName("value")
        value_label.setStyleSheet(f"""
            font-size: 20px;
            font-weight: bold;
            color: {COLORS['text_primary']};
            padding: 8px 0;
        """)
        layout.addWidget(value_label)
        
        return card
        
    def _create_action_button(self, text, callback):
        """Create an action button."""
        btn = CommandButton(text)
        btn.clicked.connect(callback)
        return btn
        
    def _create_browse_row(self, line_edit, browse_btn):
        """Create a row with a line edit and browse button."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line_edit, 1)
        layout.addWidget(browse_btn)
        return widget
        
    # ============================================================================
    # SYSTEM STATUS METHODS
    # ============================================================================
    
    def _check_system_status(self):
        """Check overall system status."""
        try:
            # Get system status
            result = get_status()
            if result.get("ok"):
                self._system_status = result
                
                # Update dashboard
                model = result.get("chat_model_default", "Unknown")
                user = result.get("user_name", "Unknown")
                self._sys_status_label.setText(f"Model: {model}\nUser: {user}")
                
                # Update persona lock status
                self._update_persona_status_display()
                
                # Update memory status
                memory_file = Path(os.environ.get("ELI_MEMORY_FILE", str(DEFAULT_MEMORY_FILE)))
                if memory_file.exists():
                    count = sum(1 for _ in open(memory_file, 'r', errors='ignore'))
                    self._memory_status_label.setText(f"{count} entries")
                else:
                    self._memory_status_label.setText("No memory file")
                
                # Update status LED
                self._status_led.set_color(COLORS["success"])
                self._status_label.setText("System OK")
            else:
                self._status_led.set_color(COLORS["error"])
                self._status_label.setText("System Error")
                
        except Exception as e:
            self._status_led.set_color(COLORS["error"])
            self._status_label.setText(f"Error: {str(e)[:30]}")
            
    def _update_persona_status_display(self):
        """Update persona lock status display."""
        try:
            result = persona_lock_status()
            if result.get("ok"):
                self._persona_lock_status = result
                reason = result.get("reason", "unknown")
                
                if reason == "ok":
                    color = COLORS["success"]
                    text = "✓ Lock OK"
                elif reason == "ok_unverified":
                    color = COLORS["warning"]
                    text = "⚠ Lock OK (unverified)"
                else:
                    color = COLORS["error"]
                    text = f"✗ Lock FAIL: {reason}"
                    
                self._persona_status_label.setText(text)
                self._persona_status_label.setStyleSheet(f"color: {color};")
                
                # Update lock details
                details = json.dumps(result.get("details", {}), indent=2)
                lock = json.dumps(result.get("lock", {}), indent=2)
                self._lock_details.setText(f"Details:\n{details}\n\nLock:\n{lock}")
                
        except Exception as e:
            self._persona_status_label.setText(f"Error: {str(e)[:30]}")
            self._persona_status_label.setStyleSheet(f"color: {COLORS['error']};")
            
    def _update_proactive_status(self):
        """Update proactive daemon status."""
        try:
            result = proactive_status()
            if result.get("ok"):
                self._proactive_status = result
                running = result.get("running", False)
                pid = result.get("pid")
                
                if running:
                    color = COLORS["success"]
                    text = f"✓ Running (PID: {pid})"
                else:
                    color = COLORS["text_muted"]
                    text = "✗ Stopped"
                    
                self._proactive_status_label.setText(text)
                self._proactive_status_label.setStyleSheet(f"color: {color};")
                self._proactive_status_display.setText(
                    f"Status: {'RUNNING' if running else 'STOPPED'}\n"
                    f"PID: {pid if pid else 'N/A'}\n"
                    f"Log: {result.get('log', 'N/A')}"
                )
                
                # Update log if running
                if running:
                    self._refresh_proactive_log()
                    
        except Exception as e:
            self._proactive_status_display.setText(f"Error checking status: {str(e)}")
            
    def _refresh_proactive_log(self):
        """Refresh proactive daemon log display."""
        try:
            log_path = Path("artifacts/proactive/daemon.log")
            if log_path.exists():
                with open(log_path, 'r', errors='ignore') as f:
                    lines = f.readlines()
                    last_lines = lines[-1000:]  # Last 1000 lines
                    self._proactive_log.setText("".join(last_lines))
                    # Scroll to bottom
                    cursor = self._proactive_log.textCursor()
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                    self._proactive_log.setTextCursor(cursor)
            else:
                self._proactive_log.setText("Log file not found.")
        except Exception as e:
            self._proactive_log.setText(f"Error reading log: {str(e)}")
            
    # ============================================================================
    # ACTION METHODS
    # ============================================================================
    
    def _send_chat_message(self):
        """Send chat message to ELI (token-streaming if available)."""
        message = self._chat_input.toPlainText().strip()
        
        # /apps helpers (keeps autocomplete in sync, and lets you inspect what's indexed)
        if message.lower().startswith("/apps"):
            cmd = message.strip()
            low = cmd.lower()
            refresh = ("refresh" in low) or (low.strip() == "/apps r")
            if refresh:
                self._open_app_names = fetch_open_app_names(execute, refresh=True)
                if hasattr(self, "_open_app_completer"):
                    self._open_app_completer.refresh()
                self._append_assistant_message(f"✅ Refreshed app index: {len(self._open_app_names)} apps.")
                self._chat_input.clear()
                return
            # show a small preview (don't spam the UI with 4000 apps)
            preview = self._open_app_names[:30] if isinstance(self._open_app_names, list) else []
            self._append_assistant_message(
                "📦 Indexed apps: "
                + str(len(self._open_app_names))
                + "\nTop matches:\n- "
                + "\n- ".join(preview)
                + "\n\nTip: type `open ` then hit Ctrl+Space for autocomplete, or use `/apps refresh`."
            )
            self._chat_input.clear()
            return

        if not message:
            return

        # Add user message to display
        self._add_chat_message("user", message)
        self._chat_input.clear()

        # Disable send button during processing
        if hasattr(self, "_chat_send_btn"):
            self._chat_send_btn.setEnabled(False)

        self._set_ui_state("THINKING")

        # Start assistant streaming placeholder
        self._begin_assistant_stream()

        # Start worker thread (Qt-safe)
        self._stream_qthread = QThread(self)
        self._stream_worker = ChatStreamWorker(message)
        self._stream_worker.moveToThread(self._stream_qthread)

        self._stream_qthread.started.connect(self._stream_worker.run)
        self._stream_worker.token.connect(self._on_stream_token)
        self._stream_worker.done.connect(self._on_stream_done)
        self._stream_worker.done.connect(self._stream_qthread.quit)
        self._stream_worker.done.connect(self._stream_worker.deleteLater)
        self._stream_qthread.finished.connect(self._stream_qthread.deleteLater)

        self._stream_qthread.start()
    
    def _append_assistant_message(self, content):
        """Append an assistant message to chat."""
        self._add_chat_message("assistant", content)
        
    def _begin_assistant_stream(self):
        """Begin streaming assistant response."""
        self._streaming_index = len(self._chat_items)
        self._chat_items.append({"role": "assistant", "ts": datetime.now().strftime("%H:%M:%S"), "content": ""})
        self._schedule_render()
        
    def _schedule_render(self):
        """Schedule a chat render (debounced)."""
        if not self._render_pending:
            self._render_pending = True
            self._render_timer.start(50)  # 50ms debounce
            
    @pyqtSlot(str)
    def _on_stream_token(self, token):
        """Handle incoming stream token."""
        if self._streaming_index is not None and self._streaming_index < len(self._chat_items):
            self._chat_items[self._streaming_index]["content"] += token
            self._schedule_render()
            
    @pyqtSlot(dict)
    def _on_stream_done(self, result):
        """Handle stream completion."""
        self._set_ui_state("IDLE")
        
        if hasattr(self, "_chat_send_btn"):
            self._chat_send_btn.setEnabled(True)
            
        if result.get("ok"):
            content = result.get("content", "")
            if self._streaming_index is not None and self._streaming_index < len(self._chat_items):
                # Ensure final content is set
                self._chat_items[self._streaming_index]["content"] = content
            else:
                self._add_chat_message("assistant", content)
                
            # Voice feedback
            if self._voice_enabled and VOICE_AVAILABLE:
                threading.Thread(target=voice_speak, args=(content[:200],), daemon=True).start()
                
            self._log_activity(f"Chat response: {len(content)} chars")
        else:
            error_msg = f"Error: {result.get('error', 'Unknown error')}"
            self._add_chat_message("system", error_msg)
            self._log_activity(f"Chat error: {error_msg}")
            
        self._streaming_index = None
        self._render_chat()

    @pyqtSlot(dict)
    def _display_chat_response(self, result):
        """Legacy non-stream response handler (kept for compatibility)."""
        self._on_stream_done(result)

    def _add_chat_message(self, role, content):
        """Add a message to the chat display (uses internal model for streaming compatibility)."""
        ts = datetime.now().strftime("%H:%M:%S")
        self._chat_items.append({"role": role, "ts": ts, "content": str(content or "")})
        self._schedule_render()

    def _render_chat(self):
        """Render chat from internal model."""
        self._render_pending = False
        
        if not hasattr(self, "_chat_display"):
            return
            
        html_parts = []
        for item in self._chat_items:
            role = item.get("role", "assistant")
            content = item.get("content", "")
            ts = item.get("ts", "")
            
            escaped_content = html.escape(content).replace('\n', '<br>')
            
            if role == "user":
                html_parts.append(f"""
                    <div style="margin-bottom: 16px;">
                        <div style="color: {COLORS['text_primary']}; font-weight: bold; margin-bottom: 4px;">
                            You <span style="color: {COLORS['text_muted']}; font-size: 12px;">{ts}</span>
                        </div>
                        <div style="color: {COLORS['text_secondary']}; padding-left: 8px;">
                            {escaped_content}
                        </div>
                    </div>
                """)
            elif role == "assistant":
                html_parts.append(f"""
                    <div style="margin-bottom: 16px;">
                        <div style="color: {COLORS['accent_blue']}; font-weight: bold; margin-bottom: 4px;">
                            ELI <span style="color: {COLORS['text_muted']}; font-size: 12px;">{ts}</span>
                        </div>
                        <div style="color: {COLORS['text_primary']}; padding-left: 8px;">
                            {escaped_content}
                        </div>
                    </div>
                """)
            else:  # system
                html_parts.append(f"""
                    <div style="margin-bottom: 16px;">
                        <div style="color: {COLORS['accent_orange']}; font-weight: bold; margin-bottom: 4px;">
                            System <span style="color: {COLORS['text_muted']}; font-size: 12px;">{ts}</span>
                        </div>
                        <div style="color: {COLORS['text_secondary']}; padding-left: 8px;">
                            {escaped_content}
                        </div>
                    </div>
                """)
        
        html_content = "".join(html_parts)
        self._chat_display.setHtml(html_content)
        
        # Scroll to bottom
        scrollbar = self._chat_display.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def _clear_chat_display(self):
        """Clear the chat display."""
        self._chat_items = []
        self._streaming_index = None
        self._chat_display.clear()
        
    def _set_ui_state(self, state):
        """Update UI state label."""
        if hasattr(self, "_ui_state_label"):
            self._ui_state_label.setText(state)

    def _tick_clock(self):
        """Update clock display."""
        if hasattr(self, "_clock_label"):
            self._clock_label.setText(datetime.now().strftime("%H:%M:%S"))
            
    def _install_hotkeys(self):
        """Install keyboard shortcuts."""
        # Ctrl+Enter to send message
        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.activated.connect(self._send_chat_message)
        
    def _voice_listen_start(self):
        """Start voice listening (STT)."""
        self._log_activity("Voice listening started")
        QMessageBox.information(self, "Voice", "Voice listening started (STT not yet implemented)")
    
    def _voice_listen_stop(self):
        """Stop voice listening."""
        self._log_activity("Voice listening stopped")
        QMessageBox.information(self, "Voice", "Voice listening stopped (STT not yet implemented)")
    
    def _toggle_voice_feedback(self, enabled):
        """Toggle voice feedback."""
        self._voice_enabled = enabled
        
    def _set_persona_lock(self):
        """Set persona lock."""
        model = self._model_combo.currentText().strip()
        modelfile = self._modelfile_edit.text().strip() or None
        
        if not model:
            QMessageBox.warning(self, "Warning", "Please enter a model name.")
            return
            
        try:
            result = persona_lock_set(model=model, modelfile_path=modelfile)
            if result.get("ok"):
                QMessageBox.information(self, "Success", "Persona lock set successfully.")
                self._update_persona_status_display()
                self._log_activity(f"Persona lock set: {model}")
            else:
                QMessageBox.critical(self, "Error", f"Failed to set lock: {result.get('error')}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Exception: {str(e)}")
            
    def _check_persona_lock(self):
        """Check persona lock status."""
        try:
            result = persona_lock_status()
            self._update_persona_status_display()
            self._log_activity("Persona lock checked")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Exception: {str(e)}")
            
    def _clear_persona_lock(self):
        """Clear persona lock."""
        reply = QMessageBox.question(
            self, "Confirm", 
            "Are you sure you want to clear the persona lock?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                result = persona_lock_clear()
                if result.get("ok"):
                    QMessageBox.information(self, "Success", "Persona lock cleared.")
                    self._update_persona_status_display()
                    self._log_activity("Persona lock cleared")
                else:
                    QMessageBox.critical(self, "Error", f"Failed to clear lock: {result.get('error')}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Exception: {str(e)}")
                
    def _refresh_models(self):
        """Refresh available models (placeholder)."""
        QMessageBox.information(self, "Info", "Model refresh would query Ollama here.")
        self._log_activity("Model refresh requested")
                
    def _browse_modelfile(self):
        """Browse for Modelfile."""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select Modelfile", str(Path.home()),
            "Modelfiles (*.Modelfile *.modelfile);;All files (*.*)"
        )
        if filename:
            self._modelfile_edit.setText(filename)
            
    def _store_memory(self):
        """Store memory entry."""
        text = self._memory_input.toPlainText().strip()
        tags = self._memory_tags.text().strip()
        
        if not text:
            QMessageBox.warning(self, "Warning", "Please enter text to store.")
            return
            
        try:
            tags_list = [t.strip() for t in tags.split(",")] if tags else []
            result = memory_store(text, tags=tags_list)
            
            if result.get("ok"):
                self._memory_input.clear()
                self._memory_tags.clear()
                QMessageBox.information(self, "Success", "Memory stored successfully.")
                self._log_activity(f"Memory stored: {text[:50]}...")
            else:
                QMessageBox.critical(self, "Error", f"Failed to store memory: {result.get('error')}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Exception: {str(e)}")
            
    def _recall_memory(self):
        """Recall memory entries."""
        query = self._memory_query.text().strip()
        limit = self._memory_limit.value()
        
        if not query:
            QMessageBox.warning(self, "Warning", "Please enter a search query.")
            return
            
        try:
            result = memory_recall(query, limit=limit)
            
            if result.get("ok"):
                hits = result.get("hits", [])
                content = result.get("content", "No results.")
                
                # Display in results area
                self._memory_results.setText(content)
                
                # Display details in popup
                details = f"Found {len(hits)} results for '{query}':\n\n"
                for i, hit in enumerate(hits, 1):
                    ts = hit.get("ts", 0)
                    time_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "Unknown"
                    text = hit.get("text", "")[:100] + "..." if len(hit.get("text", "")) > 100 else hit.get("text", "")
                    tags = ", ".join(hit.get("tags", []))
                    details += f"{i}. [{time_str}] {text}\n   Tags: {tags}\n\n"
                    
                QMessageBox.information(self, "Memory Recall", details)
                self._log_activity(f"Memory recall: '{query}' -> {len(hits)} results")
            else:
                QMessageBox.critical(self, "Error", f"Failed to recall memory: {result.get('error')}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Exception: {str(e)}")
            
    def _start_proactive(self):
        """Start proactive daemon."""
        try:
            result = proactive_start()
            if result.get("ok"):
                QMessageBox.information(self, "Success", "Proactive daemon started.")
                self._log_activity("Proactive daemon started")
                self._update_proactive_status()
            else:
                QMessageBox.critical(self, "Error", f"Failed to start: {result.get('error')}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Exception: {str(e)}")
            
    def _stop_proactive(self):
        """Stop proactive daemon."""
        try:
            result = proactive_stop()
            if result.get("ok"):
                QMessageBox.information(self, "Success", "Proactive daemon stopped.")
                self._log_activity("Proactive daemon stopped")
                self._update_proactive_status()
            else:
                QMessageBox.critical(self, "Error", f"Failed to stop: {result.get('error')}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Exception: {str(e)}")
            
    def _clear_proactive_log(self):
        """Clear proactive log display."""
        self._proactive_log.clear()
        
    def _toggle_auto_refresh(self, enabled):
        """Toggle auto-refresh of proactive status."""
        if enabled:
            self._proactive_check_timer.start(10000)
        else:
            self._proactive_check_timer.stop()
            
    def _browse_file(self, line_edit):
        """Browse for a file."""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select File", str(Path.home()),
            "All files (*.*)"
        )
        if filename:
            line_edit.setText(filename)
            
    def _save_settings(self):
        """Save settings to environment and state file."""
        try:
            # Update environment variables
            os.environ["ELI_CHAT_MODEL"] = self._settings_model.text().strip()
            os.environ["ELI_ROUTER_MODEL"] = self._settings_router_model.text().strip()
            os.environ["OLLAMA_HOST"] = self._settings_ollama_host.text().strip()
            os.environ["ELI_STATE_FILE"] = self._settings_state_file.text().strip()
            os.environ["ELI_MEMORY_FILE"] = self._settings_memory_file.text().strip()
            os.environ["ELI_LOCK_ENFORCED"] = "1" if self._settings_lock_enforced.isChecked() else "0"
            os.environ["ELI_MAX_HISTORY_MESSAGES"] = str(self._settings_max_history.value())
            os.environ["ELI_TEMPERATURE"] = str(self._settings_temperature.value())
            
            # Save to config file
            config_file = Path.home() / ".eli_config"
            with open(config_file, 'w') as f:
                f.write(f"# ELI Configuration\n")
                f.write(f"export ELI_CHAT_MODEL={os.environ['ELI_CHAT_MODEL']}\n")
                f.write(f"export ELI_ROUTER_MODEL={os.environ['ELI_ROUTER_MODEL']}\n")
                f.write(f"export OLLAMA_HOST={os.environ['OLLAMA_HOST']}\n")
                f.write(f"export ELI_STATE_FILE={os.environ['ELI_STATE_FILE']}\n")
                f.write(f"export ELI_MEMORY_FILE={os.environ['ELI_MEMORY_FILE']}\n")
                f.write(f"export ELI_LOCK_ENFORCED={os.environ['ELI_LOCK_ENFORCED']}\n")
                f.write(f"export ELI_MAX_HISTORY_MESSAGES={os.environ['ELI_MAX_HISTORY_MESSAGES']}\n")
                f.write(f"export ELI_TEMPERATURE={os.environ['ELI_TEMPERATURE']}\n")
                
            QMessageBox.information(self, "Success", "Settings saved successfully.")
            self._log_activity("Settings saved")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save settings: {str(e)}")
            
    def _reset_settings(self):
        """Reset settings to defaults."""
        reply = QMessageBox.question(
            self, "Confirm Reset",
            "Reset all settings to defaults?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._settings_model.setText("eli-persona:latest")
            self._settings_router_model.setText("")
            self._settings_ollama_host.setText("http://localhost:11434")
            self._settings_state_file.setText(str(DEFAULT_STATE_FILE))
            self._settings_memory_file.setText(str(DEFAULT_MEMORY_FILE))
            self._settings_lock_enforced.setChecked(True)
            self._settings_max_history.setValue(32)
            self._settings_temperature.setValue(0.7)
            QMessageBox.information(self, "Success", "Settings reset to defaults.")
            self._log_activity("Settings reset to defaults")
            
    def _reload_settings(self):
        """Reload settings from environment."""
        self._settings_model.setText(os.environ.get("ELI_CHAT_MODEL", ""))
        self._settings_router_model.setText(os.environ.get("ELI_ROUTER_MODEL", ""))
        self._settings_ollama_host.setText(os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
        self._settings_state_file.setText(os.environ.get("ELI_STATE_FILE", str(DEFAULT_STATE_FILE)))
        self._settings_memory_file.setText(os.environ.get("ELI_MEMORY_FILE", str(DEFAULT_MEMORY_FILE)))
        self._settings_lock_enforced.setChecked(os.environ.get("ELI_LOCK_ENFORCED", "1") != "0")
        self._settings_max_history.setValue(int(os.environ.get("ELI_MAX_HISTORY_MESSAGES", "32")))
        self._settings_temperature.setValue(float(os.environ.get("ELI_TEMPERATURE", "0.7")))
        QMessageBox.information(self, "Success", "Settings reloaded from environment.")
        self._log_activity("Settings reloaded from environment")
            
    def _test_chat(self):
        """Test chat functionality."""
        test_message = "Hello, this is a test message from the GUI. Please respond with a simple greeting."
        self._add_chat_message("user", test_message)
        self._chat_input.setText(test_message)
        self._send_chat_message()
        
    def _test_voice(self):
        """Test voice feedback."""
        if not VOICE_AVAILABLE:
            QMessageBox.warning(self, "Warning", "Voice system not available.")
            return
        
        test_text = "This is a test of the voice feedback system. The ELI Pro Audio GUI is working correctly."
        threading.Thread(target=voice_speak, args=(test_text,), daemon=True).start()
        self._log_activity("Voice test executed")
    
    def _log_activity(self, message):
        """Log activity to the activity log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._activity_log.append(f"[{timestamp}] {message}")
        
    def _quick_memory_recall(self):
        """Quick memory recall with default query."""
        self._memory_query.setText("test")
        self._recall_memory()
        
    def _run_self_test(self):
        """Run system self-test."""
        try:
            result = self_test()
            if result.get("ok"):
                details = json.dumps(result.get("results", {}), indent=2)
                QMessageBox.information(self, "Self Test", f"Self test passed!\n\nDetails:\n{details}")
                self._log_activity("Self test passed")
            else:
                details = json.dumps(result.get("results", {}), indent=2)
                QMessageBox.critical(self, "Self Test", f"Self test failed!\n\nDetails:\n{details}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Exception during self test: {str(e)}")
            
    def _clear_chat_history(self):
        """Clear chat history."""
        reply = QMessageBox.question(
            self, "Confirm Clear",
            "Clear all chat history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                result = clear_chat_history()
                if result.get("ok"):
                    self._chat_display.clear()
                    self._chat_items = []
                    QMessageBox.information(self, "Success", "Chat history cleared.")
                    self._log_activity("Chat history cleared")
                else:
                    QMessageBox.critical(self, "Error", f"Failed to clear history: {result.get('error')}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Exception: {str(e)}")
                
    def _load_state(self):
        """Load saved GUI state."""
        try:
            state_file = Path.home() / ".eli_gui_state.json"
            if state_file.exists():
                with open(state_file, 'r') as f:
                    state = json.load(f)
                    # Restore window geometry
                    if 'geometry' in state:
                        self.restoreGeometry(QByteArray.fromHex(state['geometry'].encode()))
                    # Restore other state if needed
        except Exception as e:
            print(f"Could not load GUI state: {e}")
            
    def closeEvent(self, event):
        """Save state when closing."""
        try:
            state = {
                'geometry': self.saveGeometry().toHex().data().decode()
            }
            state_file = Path.home() / ".eli_gui_state.json"
            with open(state_file, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            print(f"Could not save GUI state: {e}")
        event.accept()


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle("Fusion")
    
    # Create and show main window
    window = EliProAudioGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
