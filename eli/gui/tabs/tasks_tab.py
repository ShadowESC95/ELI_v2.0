"""ELI MKXI — Tasks tab.

The home for ADVANCED / SCHEDULED / OVERNIGHT background work: anything submitted
to the shared BackgroundTasks pool — coding jobs, and timed tasks created by
"research X overnight", "build Y at 2am", etc. (runtime.scheduled_tasks).

Shows every job (scheduled / running / done / failed / cancelled) with its kind,
status, scheduled time, and a one-line note; click a row to see its full result;
cancel a selected job (a scheduled job is un-armed; a running one is best-effort).

Threading rule: only the GUI thread touches Qt — a QTimer polls the pool's status.
"""
from __future__ import annotations

from datetime import datetime

from eli.gui.panels._qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QTextEdit, QAbstractItemView, QHeaderView, QTimer, Qt,
    QDialog, QFormLayout, QLineEdit, QComboBox, QMessageBox,
)
from eli.utils.log import get_logger

log = get_logger(__name__)

_STATUS_COLOR = {
    "scheduled": "#88c0d0", "running": "#ebcb8b", "done": "#a3be8c",
    "failed": "#bf616a", "cancelled": "#6c7086", "queued": "#b48ead",
}


class TasksTab(QWidget):
    """Live view of all background + scheduled tasks."""

    def __init__(self, parent_window=None):
        super().__init__()
        self._parent_window = parent_window
        self._rows: list = []  # row index -> job id
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1500)
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        hdr = QLabel(
            "🗓️  Advanced & scheduled tasks — coding jobs and overnight work "
            "(e.g. “research X overnight”, “build Y at 2am”). Results also surface "
            "in the Proactive panel."
        )
        hdr.setWordWrap(True)
        layout.addWidget(hdr)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "Kind", "Status", "When / Elapsed", "Note"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_select)
        layout.addWidget(self.table, stretch=3)

        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("Select a task to see its full result.")
        layout.addWidget(self.result, stretch=2)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("➕ Add task")
        add_btn.setToolTip("Schedule an overnight/timed task (same as saying it in chat).")
        add_btn.clicked.connect(self._add_task)
        btn_row.addWidget(add_btn)
        self.edit_btn = QPushButton("✏️ Edit / reschedule")
        self.edit_btn.setToolTip("Change the request or time of a selected SCHEDULED task.")
        self.edit_btn.clicked.connect(self._edit_task)
        btn_row.addWidget(self.edit_btn)
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._refresh)
        btn_row.addWidget(refresh_btn)
        self.cancel_btn = QPushButton("✕ Cancel selected")
        self.cancel_btn.clicked.connect(self._cancel_selected)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch()
        self.summary = QLabel("")
        btn_row.addWidget(self.summary)
        layout.addLayout(btn_row)

    # ── data ────────────────────────────────────────────────────────────────
    def _bt(self):
        try:
            from eli.runtime.background_tasks import get_background_tasks
            return get_background_tasks()
        except Exception:
            return None

    def _selected_jid(self):
        r = self.table.currentRow()
        if 0 <= r < len(self._rows):
            return self._rows[r]
        return None

    def _refresh(self):
        bt = self._bt()
        if bt is None:
            return
        try:
            tasks = bt.list(limit=50)
        except Exception as e:
            log.debug(f"[TASKS] list failed: {e}")
            return
        keep = self._selected_jid()
        self.table.setRowCount(len(tasks))
        self._rows = []
        for i, t in enumerate(tasks):
            jid = t.get("id")
            self._rows.append(jid)
            status = str(t.get("status") or "")
            if status == "scheduled" and t.get("scheduled_for"):
                whenc = "@ " + datetime.fromtimestamp(float(t["scheduled_for"])).strftime("%H:%M %d %b")
            else:
                whenc = f"{t.get('elapsed_s', 0)}s"
            vals = [str(jid), str(t.get("kind") or ""), status, whenc, str(t.get("note") or "")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 2:
                    col = _STATUS_COLOR.get(status)
                    if col:
                        item.setForeground(Qt.GlobalColor.white)
                self.table.setItem(i, c, item)
        # restore selection
        if keep in self._rows:
            self.table.selectRow(self._rows.index(keep))
        try:
            st = bt.stats()
            self.summary.setText(
                "  ".join(f"{k}:{v}" for k, v in (st.get("by_status") or {}).items()))
        except Exception:
            pass

    def _on_select(self):
        jid = self._selected_jid()
        bt = self._bt()
        if jid is None or bt is None:
            return
        d = bt.get(jid, include_result=True) or {}
        res = d.get("result")
        body = []
        body.append(f"Task #{jid} — {d.get('kind')} — {d.get('status')}")
        if d.get("error"):
            body.append("\nERROR:\n" + str(d["error"]))
        if res is not None:
            body.append("\nResult:\n" + _format_result(res))
        elif d.get("note"):
            body.append("\n" + str(d["note"]))
        self.result.setPlainText("\n".join(body))

    def _cancel_selected(self):
        jid = self._selected_jid()
        bt = self._bt()
        if jid is None or bt is None:
            return
        ok = bt.cancel(jid)
        self.result.setPlainText(f"Cancel job #{jid}: {'cancelled' if ok else 'could not cancel (already running/finished)'}")
        self._refresh()

    # ── add / edit (Habits-style CRUD) ───────────────────────────────────────
    def _task_dialog(self, title: str, request: str = "", when: str = "overnight",
                     kind: str = "auto"):
        """Modal for a scheduled task. Returns (request, when, kind) or None."""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        form = QFormLayout(dlg)
        req_edit = QLineEdit(request)
        req_edit.setPlaceholderText("e.g. research a new battery chemistry")
        when_edit = QLineEdit(when)
        when_edit.setPlaceholderText("overnight · tonight · at 2am · in 3 hours · tomorrow")
        kind_combo = QComboBox()
        kind_combo.addItems(["auto", "research", "code", "self_upgrade", "reflection"])
        kind_combo.setCurrentText(kind if kind in ("auto", "research", "code", "self_upgrade", "reflection") else "auto")
        form.addRow("Task:", req_edit)
        form.addRow("When:", when_edit)
        form.addRow("Kind:", kind_combo)
        btns = QHBoxLayout()
        ok = QPushButton("Schedule"); cancel = QPushButton("Cancel")
        ok.clicked.connect(dlg.accept); cancel.clicked.connect(dlg.reject)
        btns.addStretch(); btns.addWidget(cancel); btns.addWidget(ok)
        form.addRow(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        r = req_edit.text().strip()
        if not r:
            QMessageBox.warning(self, "Task", "A task description is required.")
            return None
        return r, when_edit.text().strip() or "overnight", kind_combo.currentText()

    def _schedule(self, request: str, when: str, kind: str):
        from eli.runtime.scheduled_tasks import schedule_request
        return schedule_request(request, when_spec=when, kind=(None if kind == "auto" else kind))

    def _add_task(self):
        vals = self._task_dialog("Add scheduled task")
        if not vals:
            return
        r = self._schedule(*vals)
        if r.get("ok"):
            self.result.setPlainText(f"Scheduled job #{r['job_id']} ({r['kind']}) for {r['when_human']}.")
        else:
            QMessageBox.warning(self, "Task", f"Couldn't schedule: {r.get('error')}")
        self._refresh()

    def _edit_task(self):
        jid = self._selected_jid()
        bt = self._bt()
        if jid is None or bt is None:
            return
        d = bt.get(jid) or {}
        if d.get("status") != "scheduled":
            QMessageBox.information(self, "Edit", "Only a SCHEDULED task can be edited/rescheduled.")
            return
        meta = d.get("meta") or {}
        vals = self._task_dialog("Edit / reschedule task",
                                 request=str(meta.get("request") or ""),
                                 when=str(meta.get("when_spec") or "overnight"),
                                 kind=str(meta.get("kind") or "auto"))
        if not vals:
            return
        bt.cancel(jid)                  # un-arm the old timer
        r = self._schedule(*vals)       # re-create at the new time
        if r.get("ok"):
            self.result.setPlainText(f"Rescheduled → job #{r['job_id']} ({r['kind']}) for {r['when_human']}.")
        else:
            QMessageBox.warning(self, "Task", f"Couldn't reschedule: {r.get('error')}")
        self._refresh()


def _format_result(res) -> str:
    try:
        if isinstance(res, dict):
            for k in ("answer", "report", "reflection", "script_path", "path", "content", "response"):
                if res.get(k):
                    return str(res[k])[:4000]
            import json
            return json.dumps(res, indent=2, default=str)[:4000]
        return str(res)[:4000]
    except Exception:
        return str(res)[:1000]
