"""
Ollama model selector widget for ELI GUI.

Usage — add to your toolbar in eli_pro_audio_gui_v2_0.py:

    from eli.gui.widgets.ollama_model_selector import OllamaModelSelector

    # In your toolbar init (after reasoning_mode_combo):
    self.ollama_selector = OllamaModelSelector(self)
    toolbar.addWidget(self.ollama_selector)

The widget:
  - Shows a dropdown of all installed Ollama models
  - Shows a refresh button (↻) to re-query the list
  - Shows a pull button (⬇) to pull a new model by name
  - Persists selection to ELI config ("ollama_model" key)
  - Shows Ollama status indicator (green dot = running, red = not)
  - Runs all Ollama queries in background threads (never blocks GUI)
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional

from eli.gui.qt_compat import Qt, QTimer, pyqtSignal
from eli.gui.qt_compat import QColor
from eli.gui.qt_compat import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QWidget,
)


log = logging.getLogger(__name__)


class _StatusDot(QLabel):
    """Tiny colored circle indicating Ollama running state."""

    def __init__(self, parent=None):
        super().__init__("●", parent)
        self.setFixedWidth(16)
        self.set_state(None)

    def set_state(self, running: Optional[bool]):
        if running is True:
            self.setStyleSheet("color: #44ff88; font-size: 10px;")
            self.setToolTip("Ollama running")
        elif running is False:
            self.setStyleSheet("color: #ff4444; font-size: 10px;")
            self.setToolTip("Ollama not running — start with: ollama serve")
        else:
            self.setStyleSheet("color: #888888; font-size: 10px;")
            self.setToolTip("Checking Ollama...")


class OllamaModelSelector(QWidget):
    """
    Compact toolbar widget: [● ▼ model dropdown ] [↻] [⬇]
    Emits model_changed(str) when selection changes.
    """

    model_changed = pyqtSignal(str)

    # Worker threads MUST hand results back over a signal, never QTimer.singleShot.
    # A timer started from a plain threading.Thread has no Qt event loop to run on,
    # so the callback is silently dropped — that is exactly what left this dropdown
    # permanently empty with the dot stuck on "Checking Ollama..." while the client
    # underneath was returning models fine. Signals queue to the receiver's thread.
    _models_ready = pyqtSignal(bool, list, object)
    _pull_progress = pyqtSignal(str, int)
    _pull_done = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._models_ready.connect(self._update_ui)
        self._pull_progress.connect(self._on_pull_progress)
        self._pull_done.connect(self._on_pull_done)
        self._pull_dialog = None
        self._pull_model_name = ""
        self._refresh_async()

        # Auto-refresh every 30s to catch newly pulled models
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_async)
        self._timer.start(30_000)

    # ── UI construction ───────────────────────────────────────

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(2)

        # Status dot
        self._dot = _StatusDot(self)
        layout.addWidget(self._dot)

        # Model label
        lbl = QLabel("Ollama:")
        lbl.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        layout.addWidget(lbl)

        # Model dropdown
        self._combo = QComboBox(self)
        self._combo.setMinimumWidth(160)
        self._combo.setToolTip("Select Ollama model")
        self._combo.setStyleSheet("""
            QComboBox {
                background: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #444;
                border-radius: 3px;
                padding: 2px 6px;
                font-size: 11px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1e1e2e;
                color: #cdd6f4;
                selection-background-color: #313244;
            }
        """)
        self._combo.currentTextChanged.connect(self._on_selection_changed)
        layout.addWidget(self._combo)

        # Refresh button
        btn_refresh = QPushButton("↻")
        btn_refresh.setFixedWidth(24)
        btn_refresh.setToolTip("Refresh model list")
        btn_refresh.setStyleSheet("QPushButton { background: #313244; color: #cdd6f4; border: 1px solid #444; border-radius: 3px; font-size: 13px; } QPushButton:hover { background: #45475a; }")
        btn_refresh.clicked.connect(self._refresh_async)
        layout.addWidget(btn_refresh)

        # Pull button
        btn_pull = QPushButton("⬇")
        btn_pull.setFixedWidth(24)
        btn_pull.setToolTip("Pull a new model from Ollama registry")
        btn_pull.setStyleSheet("QPushButton { background: #313244; color: #cdd6f4; border: 1px solid #444; border-radius: 3px; font-size: 13px; } QPushButton:hover { background: #45475a; }")
        btn_pull.clicked.connect(self._on_pull_clicked)
        layout.addWidget(btn_pull)

        self.setLayout(layout)

    # ── Model loading ─────────────────────────────────────────

    def _refresh_async(self):
        """Query Ollama for models in a background thread."""
        self._combo.setEnabled(False)
        threading.Thread(target=self._fetch_models, daemon=True).start()

    def _fetch_models(self):
        """Background thread: fetch models, then hand the result to the GUI thread
        over the _models_ready signal (never a timer — see the signal's comment)."""
        try:
            from eli.integrations.ollama.client import is_running, list_models, get_active_model
            running = is_running()
            models = list_models() if running else []
            active = get_active_model()
        except Exception:
            running = False
            models = []
            active = None

        # Hand back to the GUI thread. Signal, not QTimer — see _models_ready.
        self._models_ready.emit(bool(running), list(models or []), active)

    def _update_ui(self, running: bool, models: List[str], active: Optional[str]):
        """Update combo box contents (called on main thread)."""
        self._dot.set_state(running)
        self._combo.setEnabled(True)

        current = self._combo.currentText()

        self._combo.blockSignals(True)
        self._combo.clear()

        if not running:
            self._combo.addItem("Ollama not running")
            self._combo.blockSignals(False)
            return

        if not models:
            self._combo.addItem("No models installed")
            self._combo.blockSignals(False)
            return

        self._combo.addItems(models)

        # Restore selection priority: active config > previous selection > first
        restore = active or current
        idx = self._combo.findText(restore)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)

        self._combo.blockSignals(False)

    # ── Interactions ──────────────────────────────────────────

    def _on_selection_changed(self, model: str):
        if not model or "not running" in model or "No models" in model:
            return
        try:
            from eli.integrations.ollama.client import set_active_model
            set_active_model(model)
        except Exception:
            log.debug('[OLLAMA] persisting active model failed', exc_info=True)
        self.model_changed.emit(model)

    def _on_pull_clicked(self):
        model, ok = QInputDialog.getText(
            self, "Pull Ollama Model",
            "Enter model name to pull (e.g. llama3.2, mistral, gemma3:12b):",
        )
        if not ok or not model.strip():
            return

        model = model.strip()

        # Progress dialog
        progress = QProgressDialog(f"Pulling {model}...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Pulling Model")
        progress.setWindowModality(Qt.WindowModal)
        progress.setValue(0)
        progress.show()

        # The pull callbacks fire on the client's worker thread and had the same
        # QTimer-from-a-thread defect as the model list: progress never moved and the
        # dialog never closed. Route both over signals instead.
        self._pull_dialog = progress
        self._pull_model_name = model

        try:
            from eli.integrations.ollama.client import pull_model_async
            pull_model_async(model,
                             progress_cb=lambda status, pct: self._pull_progress.emit(
                                 str(status or ""), int(pct or 0)),
                             done_cb=lambda result: self._pull_done.emit(dict(result or {})))
        except Exception as e:
            progress.close()
            self._pull_dialog = None
            QMessageBox.critical(self, "Error", f"Pull failed: {e}")

    def _on_pull_progress(self, status: str, pct: int):
        """GUI thread: advance the pull dialog."""
        dlg = getattr(self, "_pull_dialog", None)
        if dlg is None:
            return
        dlg.setValue(int(pct))
        if status:
            dlg.setLabelText(f"{status}\n{pct}%")

    def _on_pull_done(self, result: dict):
        """GUI thread: close the dialog and refresh the list."""
        dlg = getattr(self, "_pull_dialog", None)
        model = getattr(self, "_pull_model_name", "") or "model"
        if dlg is not None:
            dlg.close()
        self._pull_dialog = None
        if result.get("ok"):
            QMessageBox.information(self, "Pull Complete", f"✅ {model} pulled successfully!")
            self._refresh_async()
            # Auto-select once the refreshed list has landed. This singleShot is
            # safe: _on_pull_done already runs on the GUI thread.
            QTimer.singleShot(2000, lambda: self._select_model(model))
        else:
            QMessageBox.warning(self, "Pull Failed",
                                f"❌ Failed to pull {model}:\n{result.get('error', 'Unknown error')}")

    def _select_model(self, model: str):
        idx = self._combo.findText(model)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)

    # ── Public API ────────────────────────────────────────────

    def current_model(self) -> Optional[str]:
        """Return currently selected model name, or None."""
        text = self._combo.currentText()
        if not text or "not running" in text or "No models" in text:
            return None
        return text

    def refresh(self):
        """Manually trigger a model list refresh."""
        self._refresh_async()
