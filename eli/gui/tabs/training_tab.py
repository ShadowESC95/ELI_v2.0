"""ELI v2.0 — Labs ▸ Training. The GUI half of the LoRA pipeline.

`eli/learning/` has carried a complete trainer for a long time — preflight, safety
guard, PEFT trainer, eval suite, and the DAG in `lora_pipeline` that chains them.
Its own docstring says the DAG is driven by "the GUI / scheduled task". The GUI was
never built, so the only ways in were a chat action and an overnight job, and the
human review gate the trainer requires had no interface at all: 615 candidate rows,
0 approved, training permanently refused.

This is that interface, as four steps:

    Hardware → Target → Data → Train

Each step reports what it found rather than what it assumes, because the operator
is not necessarily on the machine this was written on: any GPU vendor, any base
model family, any amount of VRAM, possibly none.

Threading: training runs on a QThread and reaches the GUI only through signals.
A queued signal is the one marshalling primitive that works from a worker —
QTimer.singleShot called off the GUI thread never fires.
"""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Optional

from eli.gui.panels._qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QTextEdit, QPlainTextEdit, QAbstractItemView, QHeaderView,
    QComboBox, QLineEdit, QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox,
    QStackedWidget, QMessageBox, QProgressBar, QSplitter, QFileDialog, QCheckBox,
    Qt, QThread, QObject, pyqtSignal,
)
from eli.utils.log import get_logger

log = get_logger(__name__)

_OK = "#a3be8c"
_WARN = "#ebcb8b"
_BAD = "#bf616a"
_DIM = "#6c7086"

_VERDICT_COLOR = {"ok": _OK, "flag": _WARN, "reject": _BAD}
_DECISION_COLOR = {"approved": _OK, "pending": _WARN, "rejected": _DIM}

# Recipes. Deliberately three, not twenty knobs — the raw parameters stay reachable
# under Advanced for anyone who wants them.
RECIPES = {
    "Light — a quick pass (minutes)": dict(
        max_steps=60, seq_len=256, batch_size=1, grad_accum=4, learning_rate=2e-4),
    "Standard — recommended": dict(
        max_steps=300, seq_len=512, batch_size=1, grad_accum=8, learning_rate=1e-4),
    "Deep — long run (hours)": dict(
        max_steps=1200, seq_len=1024, batch_size=1, grad_accum=16, learning_rate=5e-5),
}


class _TrainWorker(QObject):
    """Runs the LoRA DAG off the GUI thread."""
    progress = pyqtSignal(str)
    step = pyqtSignal(int, int, object)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, target: str, params: dict):
        super().__init__()
        self.target = target
        self.params = params
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def _on_event(self, ev: dict) -> None:
        if ev.get("type") == "step":
            self.step.emit(int(ev.get("step") or 0), int(ev.get("max_steps") or 0), ev.get("loss"))
        else:
            self.progress.emit(str(ev.get("message") or ""))
        if self._cancel:
            # Cooperative stop: the HF Trainer has no hard kill that leaves the
            # adapter directory in a sane state, so we stop at a step boundary.
            raise KeyboardInterrupt("cancelled by operator")

    def run(self) -> None:
        try:
            from eli.learning.lora_pipeline import run_pipeline
            result = run_pipeline(self.target, execute=True, on_event=self._on_event,
                                  **self.params)
            self.done.emit(result)
        except KeyboardInterrupt:
            self.failed.emit("Training cancelled.")
        except Exception as exc:
            log.debug("training failed", exc_info=True)
            self.failed.emit(f"{exc}\n\n{traceback.format_exc(limit=4)}")


class TrainingTab(QWidget):
    """Four-step wizard over eli.learning."""

    def __init__(self, parent_window=None):
        super().__init__()
        self._parent_window = parent_window
        self._queue = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[_TrainWorker] = None
        self._bases: list[dict] = []
        self._build_ui()
        self._refresh_hardware()

    # ── shell ─────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        self._crumbs = QLabel()
        self._crumbs.setStyleSheet("font-size:13px;padding:4px 2px;color:#e0e6f0;")
        root.addWidget(self._crumbs)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._page_hardware())
        self._pages.addWidget(self._page_target())
        self._pages.addWidget(self._page_data())
        self._pages.addWidget(self._page_train())
        root.addWidget(self._pages, 1)

        nav = QHBoxLayout()
        self._back_btn = QPushButton("← Back")
        self._back_btn.clicked.connect(lambda: self._goto(self._pages.currentIndex() - 1))
        self._next_btn = QPushButton("Next →")
        self._next_btn.clicked.connect(lambda: self._goto(self._pages.currentIndex() + 1))
        nav.addWidget(self._back_btn)
        nav.addStretch(1)
        self._hint = QLabel("")
        self._hint.setStyleSheet(f"color:{_DIM};")
        nav.addWidget(self._hint)
        nav.addStretch(1)
        nav.addWidget(self._next_btn)
        root.addLayout(nav)

        self._goto(0)

    def _goto(self, index: int) -> None:
        index = max(0, min(index, self._pages.count() - 1))
        self._pages.setCurrentIndex(index)
        names = ["1 · Hardware", "2 · Target", "3 · Data", "4 · Train"]
        self._crumbs.setText("   ".join(
            f"<b style='color:#88c0d0'>{n}</b>" if i == index else f"<span style='color:{_DIM}'>{n}</span>"
            for i, n in enumerate(names)))
        self._back_btn.setEnabled(index > 0)
        self._next_btn.setEnabled(index < self._pages.count() - 1)
        if index == 1:
            self._refresh_targets()
        elif index == 2:
            self._refresh_queue_header()
        elif index == 3:
            self._refresh_run_header()

    # ── step 1: hardware ──────────────────────────────────────────────────────
    def _page_hardware(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "<b>Can this machine train?</b><br>"
            "<span style='color:#6c7086'>Training a LoRA adapter teaches ELI your own "
            "conversations. It needs a GPU to be practical, and the parts below have to "
            "be present. Nothing here changes anything — it only reports.</span>"))
        self._hw_text = QTextEdit()
        self._hw_text.setReadOnly(True)
        v.addWidget(self._hw_text, 1)
        row = QHBoxLayout()
        b = QPushButton("Re-check")
        b.clicked.connect(self._refresh_hardware)
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def _refresh_hardware(self) -> None:
        lines: list[str] = []
        verdict_ok = True
        try:
            from eli.learning.lora_trainer import _accelerator, bitsandbytes_available
            acc = _accelerator()
            colour = _OK if acc["trainable"] else _WARN
            lines.append(f"<b>Accelerator</b><br><span style='color:{colour}'>{acc['name']}</span>"
                         f" &nbsp;<span style='color:{_DIM}'>({acc['vendor']}, {acc['note']})</span>")
            if acc["total_gb"]:
                lines.append(f"<b>VRAM</b><br>{acc['free_gb']} GiB free of {acc['total_gb']} GiB")
            if not acc["trainable"]:
                verdict_ok = False
                lines.append(f"<span style='color:{_WARN}'>Training would run on the CPU — "
                             f"hours to days for a run that takes minutes on a GPU.</span>")
            lines.append(f"<b>4-bit (QLoRA)</b><br>" + (
                f"<span style='color:{_OK}'>available</span> — a card too small for the "
                f"full-precision weights can still train the adapter"
                if bitsandbytes_available() else
                f"<span style='color:{_WARN}'>not installed</span> — training needs enough "
                f"VRAM for the full-precision weights (pip install bitsandbytes)"))
        except Exception as exc:
            verdict_ok = False
            lines.append(f"<span style='color:{_BAD}'>Could not probe the accelerator: {exc}</span>")

        try:
            from eli.learning.training_preflight import module_report
            mods = module_report()
            missing = [k for k, v in mods.items() if not v["available"]]
            if missing:
                verdict_ok = False
                lines.append(f"<b>Python packages</b><br><span style='color:{_BAD}'>missing: "
                             f"{', '.join(missing)}</span><br>"
                             f"<span style='color:{_DIM}'>pip install -r requirements.txt</span>")
            else:
                lines.append(f"<b>Python packages</b><br><span style='color:{_OK}'>"
                             f"all present</span> ({', '.join(mods)})")
        except Exception as exc:
            verdict_ok = False
            lines.append(f"<span style='color:{_BAD}'>Preflight failed: {exc}</span>")

        try:
            from eli.learning.base_model_resolver import discover_base_models
            found = discover_base_models()
            if found:
                lines.append("<b>Trainable base models found</b><br>" + "<br>".join(
                    f"&nbsp;&nbsp;{Path(m['path']).name} "
                    f"<span style='color:{_DIM}'>({m.get('family') or 'unknown family'}, "
                    f"{m.get('size_gb')} GB)</span>" for m in found[:8]))
            else:
                verdict_ok = False
                lines.append(f"<b>Trainable base models</b><br><span style='color:{_WARN}'>"
                             f"none found</span><br><span style='color:{_DIM}'>Training needs a "
                             f"Hugging Face model folder. A .gguf file is an inference artifact "
                             f"and cannot be trained.</span>")
        except Exception as exc:
            lines.append(f"<span style='color:{_BAD}'>Base model scan failed: {exc}</span>")

        head = (f"<div style='color:{_OK};font-size:14px'><b>Ready to train.</b></div>"
                if verdict_ok else
                f"<div style='color:{_WARN};font-size:14px'><b>Not ready yet — see below.</b></div>")
        self._hw_text.setHtml(head + "<br>" + "<br><br>".join(lines))

    # ── step 2: target ────────────────────────────────────────────────────────
    def _page_target(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "<b>What are you training?</b><br>"
            "<span style='color:#6c7086'>A target pairs a base model with its dataset and "
            "adapter. ELI will only train targets you have declared here.</span>"))

        self._target_table = QTableWidget(0, 5)
        self._target_table.setHorizontalHeaderLabels(
            ["Target", "Family", "Base model", "Data", "Status"])
        self._target_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._target_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._target_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self._target_table, 1)

        box = QGroupBox("Declare a new target")
        form = QFormLayout(box)
        self._new_name = QLineEdit()
        self._new_name.setPlaceholderText("my_model  (lowercase, no spaces)")
        form.addRow("Name", self._new_name)

        base_row = QHBoxLayout()
        self._new_base = QComboBox()
        self._new_base.setMinimumWidth(320)
        base_row.addWidget(self._new_base, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_base)
        base_row.addWidget(browse)
        bw = QWidget()
        bw.setLayout(base_row)
        form.addRow("Base model", bw)

        self._new_desc = QLineEdit()
        self._new_desc.setPlaceholderText("optional")
        form.addRow("Description", self._new_desc)

        btns = QHBoxLayout()
        add = QPushButton("Create target")
        add.clicked.connect(self._create_target)
        rm = QPushButton("Delete selected")
        rm.clicked.connect(self._delete_target)
        btns.addWidget(add)
        btns.addWidget(rm)
        btns.addStretch(1)
        bwr = QWidget()
        bwr.setLayout(btns)
        form.addRow("", bwr)
        v.addWidget(box)
        return w

    def _refresh_targets(self) -> None:
        try:
            from eli.learning.target_registry import list_targets
            from eli.learning.base_model_resolver import discover_base_models
        except Exception as exc:
            log.debug(f"[Training] registry unavailable: {exc}")
            return

        self._bases = discover_base_models()
        current = self._new_base.currentText()
        self._new_base.clear()
        for m in self._bases:
            self._new_base.addItem(
                f"{Path(m['path']).name}  —  {m.get('family') or 'unknown'}, {m.get('size_gb')} GB",
                m["path"])
        if current:
            i = self._new_base.findText(current)
            if i >= 0:
                self._new_base.setCurrentIndex(i)

        rows = list_targets()
        self._target_table.setRowCount(len(rows))
        for r, t in enumerate(rows):
            if not t["base_exists"]:
                status, colour = "base model missing", _BAD
            elif not t["family_ok"]:
                status, colour = "family mismatch", _BAD
            elif not t["dataset_exists"]:
                status, colour = "no reviewed data yet", _WARN
            else:
                status, colour = "ready", _OK
            cells = [t["name"], str(t.get("actual_family") or t.get("base_family") or "—"),
                     str(t.get("base_model_path") or ""),
                     "yes" if t["dataset_exists"] else "no", status]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 4:
                    item.setForeground(Qt.GlobalColor.white)
                    item.setToolTip(status)
                if c == 0 and t.get("builtin"):
                    item.setToolTip("Built-in target")
                self._target_table.setItem(r, c, item)
            self._target_table.item(r, 4).setText(status)
        self._target_table.resizeColumnsToContents()
        self._target_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)

    def _browse_base(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Select a Hugging Face model folder")
        if not d:
            return
        self._new_base.addItem(d, d)
        self._new_base.setCurrentIndex(self._new_base.count() - 1)

    def _selected_target(self) -> Optional[str]:
        row = self._target_table.currentRow()
        if row < 0:
            return None
        item = self._target_table.item(row, 0)
        return item.text() if item else None

    def _create_target(self) -> None:
        from eli.learning.target_registry import create_target
        name = self._new_name.text().strip()
        base = self._new_base.currentData() or self._new_base.currentText().strip()
        if not name or not base:
            QMessageBox.warning(self, "Training", "A name and a base model folder are both required.")
            return
        res = create_target(name, base, description=self._new_desc.text().strip())
        if not res.get("ok"):
            QMessageBox.warning(self, "Training", "\n".join(res.get("problems") or ["Failed."]))
            return
        self._new_name.clear()
        self._new_desc.clear()
        self._refresh_targets()
        QMessageBox.information(
            self, "Training",
            f"Target '{name}' created.\n\nNext: review the conversation data you want it "
            f"trained on, in step 3.")

    def _delete_target(self) -> None:
        from eli.learning.target_registry import delete_target
        name = self._selected_target()
        if not name:
            return
        if QMessageBox.question(
                self, "Training",
                f"Remove target '{name}'?\n\nThe adapter and dataset files stay on disk.") \
                != QMessageBox.StandardButton.Yes:
            return
        res = delete_target(name)
        if not res.get("ok"):
            QMessageBox.warning(self, "Training", "\n".join(res.get("problems") or ["Failed."]))
        self._refresh_targets()

    # ── step 3: data ──────────────────────────────────────────────────────────
    def _page_data(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "<b>Which of your conversations should it learn from?</b><br>"
            "<span style='color:#6c7086'>Nothing trains until you approve it. Rows that are "
            "obviously unusable are rejected for you; the rest are yours to judge.</span>"))

        top = QHBoxLayout()
        self._q_target = QComboBox()
        self._q_target.setMinimumWidth(180)
        top.addWidget(QLabel("Target:"))
        top.addWidget(self._q_target)
        load = QPushButton("Load candidates")
        load.clicked.connect(self._load_queue)
        top.addWidget(load)
        rebuild = QPushButton("Re-mine conversations")
        rebuild.setToolTip("Rebuild the candidate pool from ELI's stored conversations.")
        rebuild.clicked.connect(self._rebuild_candidates)
        top.addWidget(rebuild)
        top.addStretch(1)
        self._q_filter = QComboBox()
        self._q_filter.addItems(["Needs review", "All", "Approved", "Rejected", "Flagged", "Clean"])
        self._q_filter.currentTextChanged.connect(self._fill_queue_table)
        top.addWidget(QLabel("Show:"))
        top.addWidget(self._q_filter)
        v.addLayout(top)

        self._q_stats = QLabel("No candidates loaded.")
        self._q_stats.setStyleSheet(f"color:{_DIM};padding:2px;")
        v.addWidget(self._q_stats)

        split = QSplitter(Qt.Orientation.Vertical)
        self._q_table = QTableWidget(0, 4)
        self._q_table.setHorizontalHeaderLabels(["#", "Decision", "You said", "ELI replied"])
        self._q_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._q_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._q_table.itemSelectionChanged.connect(self._show_row)
        self._q_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._q_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        split.addWidget(self._q_table)

        detail = QWidget()
        dv = QVBoxLayout(detail)
        self._q_reason = QLabel("")
        self._q_reason.setWordWrap(True)
        dv.addWidget(self._q_reason)
        dv.addWidget(QLabel("You said:"))
        self._q_instr = QPlainTextEdit()
        self._q_instr.setMaximumHeight(90)
        dv.addWidget(self._q_instr)
        dv.addWidget(QLabel("ELI replied:"))
        self._q_resp = QPlainTextEdit()
        dv.addWidget(self._q_resp, 1)
        split.addWidget(detail)
        split.setSizes([320, 260])
        v.addWidget(split, 1)

        btns = QHBoxLayout()
        for label, slot, tip in (
                ("✓ Approve", lambda: self._decide("approved"), "Include this row in training"),
                ("✗ Reject", lambda: self._decide("rejected"), "Leave this row out"),
                ("Save edit", self._save_edit, "Keep your changes to this row"),
        ):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        bulk = QPushButton("Approve all clean rows")
        bulk.setToolTip("Approve every row triage found nothing wrong with. Flagged rows stay for you.")
        bulk.clicked.connect(self._approve_clean)
        btns.addWidget(bulk)
        save = QPushButton("Save reviewed set →")
        save.setToolTip("Write the approved rows as this target's training data.")
        save.clicked.connect(self._save_queue)
        btns.addWidget(save)
        v.addLayout(btns)
        return w

    def _refresh_queue_header(self) -> None:
        try:
            from eli.learning.target_registry import list_targets
            names = [t["name"] for t in list_targets()]
        except Exception:
            names = []
        current = self._q_target.currentText()
        self._q_target.clear()
        self._q_target.addItems(names)
        if current in names:
            self._q_target.setCurrentText(current)

    def _rebuild_candidates(self) -> None:
        try:
            from eli.learning.review_queue import build_candidates
            rep = build_candidates()
            QMessageBox.information(
                self, "Training",
                f"Mined {rep.get('count', 0)} candidate exchanges from your conversations.\n"
                f"Written to {rep.get('out')}")
        except Exception as exc:
            QMessageBox.warning(self, "Training", f"Could not rebuild candidates:\n{exc}")

    def _load_queue(self) -> None:
        target = self._q_target.currentText().strip()
        if not target:
            QMessageBox.warning(self, "Training", "Select a target first (step 2).")
            return
        try:
            from eli.learning.review_queue import ReviewQueue, build_candidates, candidates_path
            self._queue = ReviewQueue.for_target(target)
        except Exception as exc:
            QMessageBox.warning(self, "Training", f"Could not load candidates:\n{exc}")
            return

        # A newly declared target has no candidate pool yet. Showing an empty table
        # here reads as "you have no conversations", which is wrong — the pool has
        # simply never been mined. Offer to do it rather than leaving a dead end.
        if not self._queue.items:
            ask = QMessageBox.question(
                self, "Training",
                "No candidate conversations have been prepared yet.\n\n"
                "Mine them from ELI's stored conversations now? This reads your local "
                "databases only — nothing leaves the machine.")
            if ask != QMessageBox.StandardButton.Yes:
                self._fill_queue_table()
                return
            try:
                rep = build_candidates()
                self._queue = ReviewQueue.for_target(target)
            except Exception as exc:
                QMessageBox.warning(self, "Training", f"Could not mine conversations:\n{exc}")
                return
            if not self._queue.items:
                QMessageBox.information(
                    self, "Training",
                    f"No usable exchanges were found in your conversation history "
                    f"({rep.get('seen_candidates', 0)} looked at, "
                    f"{rep.get('count', 0)} kept).\n\nTalk to ELI some more and try again.")
        self._fill_queue_table()

    def _fill_queue_table(self) -> None:
        if self._queue is None:
            return
        mode = self._q_filter.currentText()
        rows = {
            "All": self._queue.items,
            "Needs review": self._queue.rows(decision="pending"),
            "Approved": self._queue.rows(decision="approved"),
            "Rejected": self._queue.rows(decision="rejected"),
            "Flagged": self._queue.rows(verdict="flag"),
            "Clean": self._queue.rows(verdict="ok"),
        }.get(mode, self._queue.items)

        self._visible = rows
        self._q_table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            cells = [str(item["index"]), item["decision"],
                     item["instruction"][:110].replace("\n", " "),
                     item["response"][:110].replace("\n", " ")]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if c == 1:
                    cell.setToolTip(item["reason"] or "nothing flagged")
                self._q_table.setItem(r, c, cell)
        self._q_table.resizeColumnToContents(0)
        self._q_table.resizeColumnToContents(1)

        s = self._queue.stats()
        self._q_stats.setText(
            f"{s['total']} candidates · <span style='color:{_OK}'>{s['approved']} approved</span> · "
            f"<span style='color:{_WARN}'>{s['pending']} to review</span> · "
            f"<span style='color:{_DIM}'>{s['rejected']} rejected</span> "
            f"({s['auto_rejected']} automatically) · {s['flagged']} flagged for a closer look")
        self._q_stats.setTextFormat(Qt.TextFormat.RichText)

    def _current_item(self) -> Optional[dict]:
        row = self._q_table.currentRow()
        vis = getattr(self, "_visible", [])
        if row < 0 or row >= len(vis):
            return None
        return vis[row]

    def _show_row(self) -> None:
        item = self._current_item()
        if not item:
            return
        colour = _VERDICT_COLOR.get(item["verdict"], _DIM)
        self._q_reason.setText(
            f"<span style='color:{colour}'><b>{item['verdict']}</b></span> "
            f"{item['reason']} &nbsp;<span style='color:{_DIM}'>source: {item['source']}</span>")
        self._q_instr.setPlainText(item["instruction"])
        self._q_resp.setPlainText(item["response"])

    def _decide(self, decision: str) -> None:
        item = self._current_item()
        if not item or self._queue is None:
            return
        self._queue.set_decision(item["index"], decision)
        self._fill_queue_table()

    def _save_edit(self) -> None:
        item = self._current_item()
        if not item or self._queue is None:
            return
        self._queue.edit(item["index"],
                         instruction=self._q_instr.toPlainText(),
                         response=self._q_resp.toPlainText())
        self._fill_queue_table()

    def _approve_clean(self) -> None:
        if self._queue is None:
            return
        n = self._queue.approve_clean()
        self._fill_queue_table()
        QMessageBox.information(
            self, "Training",
            f"Approved {n} rows that triage found nothing wrong with.\n\n"
            f"{self._queue.stats()['pending']} rows are still waiting on your judgement.")

    def _save_queue(self) -> None:
        if self._queue is None:
            return
        rep = self._queue.save()
        QMessageBox.information(
            self, "Training",
            f"Wrote {rep['written']} approved rows to:\n{rep['path']}\n\n"
            + ("You can train this target now (step 4)." if rep["written"]
               else "Nothing was approved, so there is nothing to train on yet."))
        self._refresh_targets()

    # ── step 4: train ─────────────────────────────────────────────────────────
    def _page_train(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "<b>Train</b><br><span style='color:#6c7086'>ELI checks every gate again before "
            "it starts. Your existing adapter is never overwritten — the result is written "
            "beside it for you to keep or discard.</span>"))

        cfg = QHBoxLayout()
        self._t_target = QComboBox()
        self._t_target.setMinimumWidth(160)
        cfg.addWidget(QLabel("Target:"))
        cfg.addWidget(self._t_target)
        self._t_recipe = QComboBox()
        self._t_recipe.addItems(list(RECIPES))
        self._t_recipe.setCurrentIndex(1)
        self._t_recipe.currentTextChanged.connect(self._apply_recipe)
        cfg.addWidget(QLabel("Recipe:"))
        cfg.addWidget(self._t_recipe)
        self._t_advanced = QCheckBox("Advanced")
        self._t_advanced.toggled.connect(lambda on: self._adv_box.setVisible(on))
        cfg.addWidget(self._t_advanced)
        cfg.addStretch(1)
        v.addLayout(cfg)

        self._adv_box = QGroupBox("Advanced")
        form = QFormLayout(self._adv_box)
        self._t_steps = QSpinBox(); self._t_steps.setRange(1, 100000)
        self._t_seq = QSpinBox(); self._t_seq.setRange(64, 8192); self._t_seq.setSingleStep(64)
        self._t_batch = QSpinBox(); self._t_batch.setRange(1, 64)
        self._t_accum = QSpinBox(); self._t_accum.setRange(1, 256)
        self._t_lr = QDoubleSpinBox(); self._t_lr.setDecimals(6)
        self._t_lr.setRange(0.000001, 0.01); self._t_lr.setSingleStep(0.00005)
        self._t_device = QComboBox(); self._t_device.addItems(["auto", "cuda", "cpu"])
        form.addRow("Steps", self._t_steps)
        form.addRow("Sequence length", self._t_seq)
        form.addRow("Batch size", self._t_batch)
        form.addRow("Gradient accumulation", self._t_accum)
        form.addRow("Learning rate", self._t_lr)
        form.addRow("Device", self._t_device)
        self._adv_box.setVisible(False)
        v.addWidget(self._adv_box)
        self._apply_recipe(self._t_recipe.currentText())

        self._t_plan = QLabel("")
        self._t_plan.setWordWrap(True)
        self._t_plan.setStyleSheet("padding:6px;")
        v.addWidget(self._t_plan)

        self._t_bar = QProgressBar()
        self._t_bar.setVisible(False)
        v.addWidget(self._t_bar)

        self._t_log = QTextEdit()
        self._t_log.setReadOnly(True)
        self._t_log.setStyleSheet("font-family:monospace;font-size:11px;")
        v.addWidget(self._t_log, 1)

        row = QHBoxLayout()
        self._t_check = QPushButton("Check readiness")
        self._t_check.clicked.connect(self._dry_run)
        row.addWidget(self._t_check)
        self._t_start = QPushButton("Start training")
        self._t_start.clicked.connect(self._start)
        row.addWidget(self._t_start)
        self._t_cancel = QPushButton("Cancel")
        self._t_cancel.setEnabled(False)
        self._t_cancel.clicked.connect(self._cancel)
        row.addWidget(self._t_cancel)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def _apply_recipe(self, name: str) -> None:
        r = RECIPES.get(name)
        if not r:
            return
        self._t_steps.setValue(r["max_steps"])
        self._t_seq.setValue(r["seq_len"])
        self._t_batch.setValue(r["batch_size"])
        self._t_accum.setValue(r["grad_accum"])
        self._t_lr.setValue(r["learning_rate"])

    def _refresh_run_header(self) -> None:
        try:
            from eli.learning.target_registry import list_targets
            names = [t["name"] for t in list_targets()]
        except Exception:
            names = []
        current = self._t_target.currentText()
        self._t_target.clear()
        self._t_target.addItems(names)
        if current in names:
            self._t_target.setCurrentText(current)

    def _params(self) -> dict:
        return dict(max_steps=self._t_steps.value(), seq_len=self._t_seq.value(),
                    batch_size=self._t_batch.value(), grad_accum=self._t_accum.value(),
                    learning_rate=self._t_lr.value(), device=self._t_device.currentText())

    def _dry_run(self) -> None:
        target = self._t_target.currentText().strip()
        if not target:
            return
        self._t_log.clear()
        try:
            from eli.learning.lora_pipeline import run_pipeline
            res = run_pipeline(target, execute=False, **self._params())
        except Exception as exc:
            self._t_log.append(f"<span style='color:{_BAD}'>Readiness check failed: {exc}</span>")
            return
        self._t_log.append(f"<b>{res['summary']}</b>")
        blockers: list[str] = []
        for st in res["stages"]:
            d = st["detail"]
            self._t_log.append(f"  {st['stage']}: {'ok' if st['ok'] else 'FAILED'}")
            for key in ("problems", "not_ready"):
                for p in (d.get(key) or []):
                    blockers.append(str(p))
                    self._t_log.append(f"<span style='color:{_WARN}'>    · {p}</span>")
        if blockers:
            self._t_plan.setText(
                f"<span style='color:{_WARN}'>Not ready: {blockers[0]}</span>")
        else:
            self._t_plan.setText(f"<span style='color:{_OK}'>All gates pass — ready to train.</span>")

        try:
            from eli.learning.lora_trainer import _pick_device
            from eli.learning.lora_trainer_guard import resolve_target, _project_path
            base = _project_path(resolve_target(target).base_model_path)
            d = _pick_device(self._t_device.currentText(), base_model_path=base,
                             seq_len=self._t_seq.value(), batch_size=self._t_batch.value())
            self._t_log.append(f"\n<b>Device</b>: {d['selected']} — {d['reason']}")
        except Exception:
            log.debug("[Training] device preview unavailable", exc_info=True)

    def _start(self) -> None:
        if self._thread is not None:
            return
        target = self._t_target.currentText().strip()
        if not target:
            return
        if QMessageBox.question(
                self, "Training",
                f"Start training '{target}'?\n\nThis uses the GPU heavily and can take from "
                f"minutes to hours. ELI stays usable but will be slower.") \
                != QMessageBox.StandardButton.Yes:
            return

        self._t_log.clear()
        self._t_log.append("Starting…")
        self._t_bar.setVisible(True)
        self._t_bar.setRange(0, 0)
        self._t_start.setEnabled(False)
        self._t_check.setEnabled(False)
        self._t_cancel.setEnabled(True)

        self._thread = QThread(self)
        self._worker = _TrainWorker(target, self._params())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.step.connect(self._on_step)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()
            self._t_log.append("Cancelling at the next step boundary…")

    def _on_progress(self, message: str) -> None:
        self._t_log.append(message)

    def _on_step(self, step: int, total: int, loss) -> None:
        if total:
            self._t_bar.setRange(0, total)
            self._t_bar.setValue(step)
        text = f"step {step}" + (f"/{total}" if total else "")
        if loss is not None:
            text += f"   loss {loss:.4f}"
        self._t_log.append(text)

    def _teardown(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None
        self._t_bar.setVisible(False)
        self._t_start.setEnabled(True)
        self._t_check.setEnabled(True)
        self._t_cancel.setEnabled(False)

    def _on_done(self, result: Any) -> None:
        self._teardown()
        self._t_log.append(f"\n<b>{result.get('summary')}</b>")
        if result.get("executed"):
            out = ""
            for st in result.get("stages", []):
                if st["stage"] == "train":
                    out = st["detail"].get("output_dir") or ""
            self._t_plan.setText(
                f"<span style='color:{_OK}'>Adapter written to {out}</span>")
            QMessageBox.information(
                self, "Training",
                f"Training finished.\n\nThe new adapter is at:\n{out}\n\n"
                f"Your existing adapter was not touched. To use the new one it still has "
                f"to be merged into the base model and converted to GGUF — see "
                f"training/README.md.")
        else:
            self._t_plan.setText(
                f"<span style='color:{_WARN}'>Training did not run — the gates above explain why.</span>")

    def _on_failed(self, message: str) -> None:
        self._teardown()
        self._t_log.append(f"<span style='color:{_BAD}'>{message}</span>")
        self._t_plan.setText(f"<span style='color:{_BAD}'>Training failed.</span>")
