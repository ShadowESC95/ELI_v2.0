"""ELI MKXI — Coding tab.

A dedicated GUI surface for the verified coding agent (eli/coding): type a task,
pick a language, and ELI runs the full pipeline (plan → DAG/tree-search →
execute → repair → bug-memory) on a background worker so the UI never blocks.
A live job list shows running/finished jobs; clicking one shows its result.

Threading rule: only the GUI thread (via QTimer) touches Qt widgets. The actual
work runs on the shared BackgroundTasks pool; we poll its status.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from eli.utils.log import get_logger

log = get_logger(__name__)

# ── Qt binding detection (mirror labs_tab: prefer the live binding) ──────────
_eli_qt_pref = str(os.environ.get("ELI_QT_API") or "").strip()
if "PySide6" in sys.modules:
    _ORDER = ["PySide6", "PyQt6", "PyQt5"]
elif "PyQt6" in sys.modules:
    _ORDER = ["PyQt6", "PySide6", "PyQt5"]
elif "PyQt5" in sys.modules:
    _ORDER = ["PyQt5", "PySide6", "PyQt6"]
elif _eli_qt_pref in {"PySide6", "PyQt6", "PyQt5"}:
    _ORDER = [_eli_qt_pref] + [x for x in ("PySide6", "PyQt6", "PyQt5") if x != _eli_qt_pref]
else:
    _ORDER = ["PySide6", "PyQt6", "PyQt5"]

_QT = None
for _cand in _ORDER:
    try:
        if _cand == "PySide6":
            from PySide6.QtWidgets import (
                QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
                QPlainTextEdit, QListWidget, QListWidgetItem, QSplitter, QGroupBox)
            from PySide6.QtCore import Qt, QTimer
            from PySide6.QtGui import QFont
        elif _cand == "PyQt6":
            from PyQt6.QtWidgets import (
                QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
                QPlainTextEdit, QListWidget, QListWidgetItem, QSplitter, QGroupBox)
            from PyQt6.QtCore import Qt, QTimer
            from PyQt6.QtGui import QFont
        else:
            from PyQt5.QtWidgets import (
                QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
                QPlainTextEdit, QListWidget, QListWidgetItem, QSplitter, QGroupBox)
            from PyQt5.QtCore import Qt, QTimer
            from PyQt5.QtGui import QFont
        _QT = _cand
        break
    except Exception:
        continue

if _QT is None:  # headless / no Qt — provide a stub so import never crashes
    class CodingTab:  # type: ignore
        def __init__(self, *a, **k):
            raise RuntimeError("Qt not available; CodingTab cannot be constructed")
else:
    _LANGS = ["python", "bash", "javascript", "typescript", "ruby", "go", "lua"]

    class CodingTab(QWidget):
        """Coding agent workspace: task in → verified solution + live jobs."""

        def __init__(self, parent_window=None):
            super().__init__()
            self.parent_window = parent_window
            self._watched = {}  # job_id → last status (to refresh result box on completion)
            self._build()
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._refresh_jobs)
            self._timer.start(1200)

        # ── UI ───────────────────────────────────────────────────────────────
        def _build(self):
            root = QVBoxLayout(self)
            title = QLabel("🧩  Coding Agent — plan → DAG/tree-search → execute → verify → repair")
            f = QFont(); f.setBold(True); title.setFont(f)
            root.addWidget(title)
            root.addWidget(QLabel("Verified, runnable code via the local model. Heavy tasks run in the "
                                  "background automatically — watch the Jobs list."))

            # Input row
            in_box = QGroupBox("Task")
            in_l = QVBoxLayout(in_box)
            self.prompt = QPlainTextEdit()
            self.prompt.setPlaceholderText("e.g. Implement binary search and test it; or: build a tokenizer, "
                                           "a parser that uses it, and an evaluator.")
            self.prompt.setMinimumHeight(80)
            in_l.addWidget(self.prompt)
            row = QHBoxLayout()
            self.lang = QComboBox(); self.lang.addItems(_LANGS)
            row.addWidget(QLabel("Language:")); row.addWidget(self.lang)
            self.solve_btn = QPushButton("Solve (verified)")
            self.solve_btn.clicked.connect(self._on_solve)
            row.addWidget(self.solve_btn); row.addStretch(1)
            in_l.addLayout(row)
            root.addWidget(in_box)

            # Split: jobs list | result
            split = QSplitter(Qt.Orientation.Horizontal if hasattr(Qt, "Orientation") else Qt.Horizontal)
            jobs_box = QGroupBox("Background jobs")
            jl = QVBoxLayout(jobs_box)
            self.jobs = QListWidget()
            self.jobs.itemClicked.connect(self._on_job_clicked)
            jl.addWidget(self.jobs)
            split.addWidget(jobs_box)

            res_box = QGroupBox("Result")
            rl = QVBoxLayout(res_box)
            self.result = QPlainTextEdit(); self.result.setReadOnly(True)
            mono = QFont("monospace"); mono.setStyleHint(QFont.StyleHint.Monospace if hasattr(QFont, "StyleHint") else QFont.Monospace)
            self.result.setFont(mono)
            rl.addWidget(self.result)
            split.addWidget(res_box)
            split.setSizes([260, 600])
            root.addWidget(split, 1)

        # ── actions ────────────────────────────────────────────────────────--
        def _on_solve(self):
            task = self.prompt.toPlainText().strip()
            if not task:
                return
            lang = self.lang.currentText()
            try:
                from eli.runtime.background_tasks import get_background_tasks
                bt = get_background_tasks()

                def _work():
                    from eli.execution.executor_enhanced import execute
                    # Force foreground inside the worker (we ARE the background here).
                    return execute("CODE_SOLVE", {"description": task, "language": lang,
                                                  "_no_background": True})
                jid = bt.submit(f"CODE_SOLVE: {task[:50]}", _work)
                self._watched[jid] = "queued"
                self.result.setPlainText(f"Started job #{jid} — running the coding pipeline in the background…")
            except Exception as exc:
                self.result.setPlainText(f"Could not start job: {exc}")

        def _refresh_jobs(self):
            try:
                from eli.runtime.background_tasks import get_background_tasks
                jobs = get_background_tasks().list(limit=20)
            except Exception:
                return
            self.jobs.clear()
            for j in jobs:
                item = QListWidgetItem(f"#{j['id']} [{j['status']}] {j['name']} ({j['elapsed_s']}s)")
                item.setData(Qt.ItemDataRole.UserRole if hasattr(Qt, "ItemDataRole") else Qt.UserRole, j["id"])
                self.jobs.addItem(item)
                # auto-show a watched job's result when it finishes
                prev = self._watched.get(j["id"])
                if prev is not None and prev not in ("done", "failed") and j["status"] in ("done", "failed"):
                    self._watched[j["id"]] = j["status"]
                    self._show_job(j["id"])

        def _on_job_clicked(self, item):
            role = Qt.ItemDataRole.UserRole if hasattr(Qt, "ItemDataRole") else Qt.UserRole
            self._show_job(item.data(role))

        def _show_job(self, jid):
            try:
                from eli.runtime.background_tasks import get_background_tasks
                t = get_background_tasks().get(int(jid))
            except Exception:
                t = None
            if not t:
                self.result.setPlainText(f"No job #{jid}.")
                return
            if t["status"] == "failed":
                self.result.setPlainText(f"Job #{jid} FAILED:\n{t.get('error','')}")
                return
            if t["status"] != "done":
                self.result.setPlainText(f"Job #{jid} is {t['status']} ({t['elapsed_s']}s)…")
                return
            r = t.get("result") or {}
            header = (f"Job #{jid} — {'solved' if r.get('solved') else 'best-effort'} "
                      f"(score {r.get('score')}); saved: {r.get('script_path','?')}\n"
                      f"plan: {r.get('plan')}\n" + "─" * 60 + "\n")
            self.result.setPlainText(header + (r.get("code") or "(no code)"))
