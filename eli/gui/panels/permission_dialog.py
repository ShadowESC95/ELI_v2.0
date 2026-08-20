"""The consent dialog — the moment the operator actually decides.

Modelled on the Android runtime-permission prompt because that pattern earned its
shape: asked at the point of use rather than buried in an install screen, phrased
as what the app can do to you rather than which API it calls, and answerable with
"just this once" so that granting something is not automatically permanent.

Four answers, and the two refusals are distinct on purpose. "Not now" is a soft no
that will be asked again next time; "Never" is remembered and the plugin is never
allowed to ask again. Without the second, a plugin can nag until the operator
clicks the wrong button out of fatigue.

Wording rules this file keeps:
  * Never imply ELI vetted the plugin. Nobody curated the marketplace.
  * Name the plugin every time, so consent cannot be harvested by whichever plugin
    happens to ask while the operator is thinking about a different one.
  * The risk colour is decoration; the sentence has to carry the meaning on its own.
"""
from __future__ import annotations

import threading
from typing import Any, Dict

from eli.gui.panels._qt import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, Qt,
    QObject, QThread, QApplication, pyqtSignal, QMetaObject, Q_ARG, Slot,
)
from eli.plugins.permissions import ALLOW_ALWAYS, ALLOW_ONCE, DENY_ONCE, DENY_ALWAYS

_RISK_COLOUR = {
    "low": "#a3be8c",
    "medium": "#ebcb8b",
    "high": "#d08770",
    "critical": "#bf616a",
}


class PermissionDialog(QDialog):
    """Ask once, for one capability, for one plugin."""

    def __init__(self, request: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._request = request
        self._answer = DENY_ONCE          # closing the window is a refusal, not a grant
        self.setWindowTitle("Plugin permission request")
        self.setMinimumWidth(460)
        self._build()

    def _build(self) -> None:
        r = self._request
        risk = str(r.get("risk", "high"))
        colour = _RISK_COLOUR.get(risk, "#bf616a")

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)

        plugin = str(r.get("plugin_id", "A plugin"))
        head = QLabel(f"<div style='font-size:15px'><b>Allow <span style='color:#88c0d0'>"
                      f"{plugin}</span> to:</b></div>")
        head.setWordWrap(True)
        v.addWidget(head)

        title = QLabel(f"<div style='font-size:17px;color:{colour}'><b>"
                       f"{r.get('title', 'do something')}</b></div>")
        title.setWordWrap(True)
        v.addWidget(title)

        detail = QLabel(str(r.get("detail", "")))
        detail.setWordWrap(True)
        detail.setStyleSheet("color:#d8dee9;")
        v.addWidget(detail)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color:#3b4252;")
        v.addWidget(line)

        why = QLabel(f"<span style='color:{colour}'><b>{risk.upper()} RISK</b></span> — "
                     f"{r.get('why_risky', '')}")
        why.setWordWrap(True)
        v.addWidget(why)

        caution = QLabel(
            "<span style='color:#6c7086'>This plugin was not written or checked by ELI. "
            "Community plugins run on your computer with the access you grant here.</span>")
        caution.setWordWrap(True)
        v.addWidget(caution)

        v.addSpacing(4)

        # Order matters: the safe answer sits under the cursor's resting place, and
        # the permanent grant is deliberately not the default button.
        row1 = QHBoxLayout()
        allow_once = QPushButton("Allow once")
        allow_once.setToolTip("Allow this now. You will be asked again next time.")
        allow_once.clicked.connect(lambda: self._answer_with(ALLOW_ONCE))
        row1.addWidget(allow_once)

        allow_always = QPushButton("Always allow")
        allow_always.setToolTip("Allow this every time, without asking again. "
                                "You can revoke it in the Marketplace.")
        allow_always.clicked.connect(lambda: self._answer_with(ALLOW_ALWAYS))
        row1.addWidget(allow_always)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        deny = QPushButton("Not now")
        deny.setToolTip("Refuse this time. You will be asked again next time.")
        deny.clicked.connect(lambda: self._answer_with(DENY_ONCE))
        deny.setDefault(True)
        row2.addWidget(deny)

        never = QPushButton("Never allow")
        never.setToolTip("Refuse permanently. This plugin will never be able to ask again.")
        never.clicked.connect(lambda: self._answer_with(DENY_ALWAYS))
        row2.addWidget(never)
        v.addLayout(row2)

    def _answer_with(self, decision: str) -> None:
        self._answer = decision
        self.accept()

    def answer(self) -> str:
        return self._answer


def prompt_for_permission(request: Dict[str, Any], parent=None) -> str:
    """The callable registered with `permissions.set_prompt_handler`.

    Must run on the GUI thread — a plugin calling from a worker would otherwise
    construct a QDialog off-thread. Callers that may be on a worker should marshal
    through a queued signal first.
    """
    dlg = PermissionDialog(request, parent=parent)
    dlg.exec()
    return dlg.answer()


class ConsentBridge(QObject):
    """Marshals a permission request onto the GUI thread and waits for the answer.

    A plugin can ask for a capability from anywhere — a worker thread, a background
    task, the proactive daemon. Constructing a QDialog off the GUI thread is
    undefined behaviour, and QTimer.singleShot from a worker never fires, so the
    only correct primitive is a queued signal plus a wait.

    The wait is bounded. If the GUI never answers — the window is gone, the app is
    shutting down — the request DENIES rather than hanging the calling thread, which
    keeps the fail-closed rule true even when the UI is the thing that failed.
    """

    _ask = pyqtSignal(object)

    def __init__(self, parent=None, *, timeout_s: float = 300.0):
        super().__init__(parent)
        self._timeout_s = float(timeout_s)
        self._answers: Dict[int, str] = {}
        self._events: Dict[int, threading.Event] = {}
        self._lock = threading.Lock()
        self._seq = 0
        self._ask.connect(self._on_gui_thread, Qt.ConnectionType.QueuedConnection)

    def _on_gui_thread(self, token: int) -> None:
        request = self._pending.pop(token, None)
        answer = DENY_ONCE
        try:
            if request is not None:
                answer = prompt_for_permission(request, parent=self.parent())
        except Exception:
            answer = DENY_ONCE
        finally:
            with self._lock:
                self._answers[token] = answer
                ev = self._events.get(token)
            if ev is not None:
                ev.set()

    def handler(self, request: Dict[str, Any]) -> str:
        """The callable to pass to permissions.set_prompt_handler()."""
        app = QApplication.instance()
        on_gui_thread = app is not None and QThread.currentThread() == app.thread()
        if on_gui_thread:
            return prompt_for_permission(request, parent=self.parent())

        with self._lock:
            self._seq += 1
            token = self._seq
            ev = threading.Event()
            self._events[token] = ev
        self._pending[token] = request
        self._ask.emit(token)

        if not ev.wait(self._timeout_s):
            with self._lock:
                self._events.pop(token, None)
                self._answers.pop(token, None)
            self._pending.pop(token, None)
            return DENY_ONCE          # nobody answered — refuse, never assume yes

        with self._lock:
            answer = self._answers.pop(token, DENY_ONCE)
            self._events.pop(token, None)
        return answer

    _pending: Dict[int, Dict[str, Any]] = {}


def install_consent_ui(parent=None) -> "ConsentBridge":
    """Register the GUI consent dialog as ELI's permission prompt.

    Called once from the main window. Until this runs, `permissions.check()` denies
    everything, which is the correct behaviour for a headless or API-only process.
    """
    from eli.plugins.permissions import set_prompt_handler
    bridge = ConsentBridge(parent)
    bridge._pending = {}
    set_prompt_handler(bridge.handler)
    return bridge


__all__ = ["PermissionDialog", "prompt_for_permission", "ConsentBridge",
           "install_consent_ui"]
