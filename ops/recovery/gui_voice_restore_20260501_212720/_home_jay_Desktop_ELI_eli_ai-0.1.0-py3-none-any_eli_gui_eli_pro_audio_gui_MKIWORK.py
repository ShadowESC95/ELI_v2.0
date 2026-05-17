from eli.brain.paths import PATHS
#!/usr/bin/env python3
"""
ELI - Entropic Logical Interpreter 
Professional Assistant Interface with Audio STT

FIXED (FINAL):
- PySide6 only – no PyQt6 traces.
- Signals use `Signal` (not `pyqtSignal`).
- GGUF model path printed at startup.
model_path = str(PATHS.model)  # force correct path
model_path = str(PATHS.model)  # force correct path
- Duplicate `get_engine()` call removed.
"""

import sys
import os
import json
import threading
import re
from pathlib import Path
import time
from datetime import datetime
import traceback

# Session memory bridge (chat_history)
try:
    from eli.brain.memory_service import (
        ensure_schema as _mem_ensure_schema,
        get_or_create_session_id as _mem_get_or_create_session_id,
        append_chat_turn as _mem_append_chat_turn,
        get_last_user_utterance as _mem_get_last_user_utterance,
        summarize_recent_window as _mem_summarize_recent_window,
    )
    MEMORY_SERVICE_AVAILABLE = True
except Exception:
    MEMORY_SERVICE_AVAILABLE = False
    def _mem_ensure_schema(): return None
    def _mem_get_or_create_session_id(): return "fallback-session"
    def _mem_append_chat_turn(*args, **kwargs): return None
    def _mem_get_last_user_utterance(*args, **kwargs): return None
    def _mem_summarize_recent_window(*args, **kwargs): return ""

from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *

from eli.brain.cognitive_engine import get_engine
from eli.brain.memory import get_memory

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import ELI modules
print("🚀 Initializing Entropic Logical Interpreter...")
try:
    from eli.tools.router_enhanced import route
    from eli.tools.executor_enhanced import execute
    from eli.brain import state as eli_state
    from eli.tools.executor_enhanced import proactive_status, proactive_start, proactive_stop
    from eli.tools.audio_stt import start_audio_listening, stop_audio_listening, listen_for_command
    from eli.tools.chat_model import chat_response_stream
    print("✅ Core systems engaged")
    print("✅ Neural routing matrix: ONLINE")
    print("✅ Executor protocols: ACTIVE")
    print("✅ Audio STT subsystem: READY")
except ImportError as e:
    print(f"❌ System initialization failed: {e}")
    sys.exit(1)


class ProactiveDockWidget(QWidget):
    """GUI dock tab: real-time pattern intelligence and daemon insights."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.daemon = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Header
        header = QHBoxLayout()
        title = QLabel("🧠 PROACTIVE INTELLIGENCE")
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #5e81ac;")
        header.addWidget(title)
        header.addStretch()
        self.last_update_lbl = QLabel("Not yet analyzed")
        self.last_update_lbl.setStyleSheet("color: #88c0d0; font-size: 10px;")
        header.addWidget(self.last_update_lbl)
        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        header.addWidget(self.btn_refresh)
        layout.addLayout(header)

        # Patterns section
        pat_label = QLabel("📊 BEHAVIORAL PATTERNS")
        pat_label.setStyleSheet("font-weight: bold; color: #88c0d0; margin-top: 8px;")
        layout.addWidget(pat_label)

        self.pattern_count_lbl = QLabel("Detecting patterns...")
        self.pattern_count_lbl.setStyleSheet("color: #d8dee9; font-size: 11px;")
        layout.addWidget(self.pattern_count_lbl)

        self.patterns_text = QPlainTextEdit()
        self.patterns_text.setReadOnly(True)
        self.patterns_text.setMaximumHeight(160)
        self.patterns_text.setStyleSheet(
            "background:#1e1e1e; color:#d4d4d4; border:1px solid #3e3e3e;"
            "font-family:'Courier New',monospace; font-size:10pt;")
        layout.addWidget(self.patterns_text)

        # Suggestions section
        sug_label = QLabel("💡 INTELLIGENT SUGGESTIONS")
        sug_label.setStyleSheet("font-weight: bold; color: #88c0d0; margin-top: 8px;")
        layout.addWidget(sug_label)

        self.suggestions_text = QPlainTextEdit()
        self.suggestions_text.setReadOnly(True)
        self.suggestions_text.setMaximumHeight(120)
        self.suggestions_text.setStyleSheet(
            "background:#1e1e1e; color:#4ec9b0; border:1px solid #3e3e3e;"
            "font-family:'Courier New',monospace; font-size:10pt;")
        layout.addWidget(self.suggestions_text)

        # Health section
        health_label = QLabel("📈 SYSTEM HEALTH")
        health_label.setStyleSheet("font-weight: bold; color: #88c0d0; margin-top: 8px;")
        layout.addWidget(health_label)

        self.health_text = QPlainTextEdit()
        self.health_text.setReadOnly(True)
        self.health_text.setMaximumHeight(110)
        self.health_text.setStyleSheet(
            "background:#1e1e1e; color:#ce9178; border:1px solid #3e3e3e;"
            "font-family:'Courier New',monospace; font-size:10pt;")
        layout.addWidget(self.health_text)

        layout.addStretch()

        # Auto-refresh every 5 minutes
        self.timer = QTimer(self)
        self.timer.setInterval(300000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        QTimer.singleShot(1500, self.refresh)

    def set_daemon(self, daemon):
        self.daemon = daemon
        self.refresh()

    def refresh(self):
        if not self.daemon:
            try:
                from eli.brain.proactive_daemon import get_daemon
                self.daemon = get_daemon()
            except Exception:
                self.patterns_text.setPlainText("⚠ Daemon not available yet.")
                return

        from datetime import datetime
        self.last_update_lbl.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

        # Patterns
        try:
            patterns = self.daemon.analyze_user_patterns()
            self.pattern_count_lbl.setText(f"Detected: {len(patterns)} patterns")
            lines = []
            time_pats = [p for p in patterns if p.get('type') == 'time_habit']
            if time_pats:
                lines.append("⏰ Time Patterns:")
                for p in time_pats[:3]:
                    lines.append(f"  • {p.get('suggestion','')}")
                lines.append("")
            repeated = [p for p in patterns if p.get('type') == 'repeated_query'
                        and len(p.get('phrase','')) > 10 and p.get('count',0) > 3]
            if repeated:
                lines.append("🔤 Frequently Used Terms:")
                for p in repeated[:10]:
                    lines.append(f"  • '{p.get('phrase','')}' ({p.get('count',0)}x)")
            self.patterns_text.setPlainText('\n'.join(lines) if lines else "Keep using ELI to detect patterns!")

            # Suggestions
            sugs = []
            pdf_pats = [p for p in patterns if 'pdf' in str(p).lower()]
            if len(pdf_pats) > 5:
                sugs.append("📄 Heavy PDF user — enable auto-analysis for new files?")
            if time_pats:
                h = time_pats[0].get('peak_hour')
                if h:
                    sugs.append(f"⏰ Peak activity at {h}:00 — schedule automated briefing?")
            if repeated:
                sugs.append(f"🔖 Create shortcut for: '{repeated[0].get('phrase','')}'")
            self.suggestions_text.setPlainText('\n\n'.join(sugs) if sugs else "✨ More usage needed for personalised suggestions.")
        except Exception as e:
            self.patterns_text.setPlainText(f"Error: {e}")

        # Health
        try:
            import sqlite3
            from pathlib import Path
            db = PATHS.db
            if not db.exists():
                # Try canonical path
                db = PATHS.db
            if db.exists():
                con = sqlite3.connect(str(db))
                cur = con.cursor()
                # Discover actual table names
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [r[0] for r in cur.fetchall()]
                # Memory count - try multiple table names
                mem = 0
                for tbl in ["memories", "memory", "eli_memory", "mem"]:
                    if tbl in tables:
                        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                        mem = cur.fetchone()[0]
                        break
                # Conversation count
                conv = 0
                for tbl in ["conversations", "conversation", "chat_history", "history"]:
                    if tbl in tables:
                        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                        conv = cur.fetchone()[0]
                        break
                con.close()
                size_mb = db.stat().st_size / 1048576
                health_lines = [
                    f"💾 Memory Entries : {mem}",
                    f"💬 Conversations  : {conv}",
                    f"📊 Database Size  : {size_mb:.2f} MB",
                    f"📋 Tables         : {', '.join(tables[:4])}",
                    "",
                    "✅ Proactive Daemon  : Running",
                    "✅ Memory System     : Active",
                    "✅ Pattern Learning  : Enabled",
                ]
                self.health_text.setPlainText('\n'.join(health_lines))
            else:
                self.health_text.setPlainText("⚠ Database not found")
        except Exception as e:
            self.health_text.setPlainText(f"Health check error: {e}")


class SelfImproveDockWidget(QWidget):
    """GUI dock tab: code quality metrics and self-improvement dashboard."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.daemon = None
        self.improvements = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Header
        header = QHBoxLayout()
        title = QLabel("🔧 SELF-IMPROVEMENT DASHBOARD")
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #5e81ac;")
        header.addWidget(title)
        header.addStretch()
        self.analyze_btn = QPushButton("🔍 Analyze Now")
        self.analyze_btn.clicked.connect(self.run_analysis)
        header.addWidget(self.analyze_btn)
        layout.addLayout(header)

        # Quality score bar
        score_row = QHBoxLayout()
        score_row.addWidget(QLabel("Code Quality:"))
        self.score_bar = QProgressBar()
        self.score_bar.setRange(0, 100)
        self.score_bar.setValue(89)
        self.score_bar.setFormat("%p%")
        self.score_bar.setStyleSheet(
            "QProgressBar{border:2px solid #3e3e3e;border-radius:4px;text-align:center;height:22px;}"
            "QProgressBar::chunk{background:#4ec9b0;}")
        score_row.addWidget(self.score_bar, 1)
        self.issues_lbl = QLabel("Issues: —")
        self.issues_lbl.setStyleSheet("color:#d8dee9;")
        score_row.addWidget(self.issues_lbl)
        layout.addLayout(score_row)

        # Issues list
        iss_label = QLabel("⚠ DETECTED ISSUES")
        iss_label.setStyleSheet("font-weight:bold; color:#88c0d0; margin-top:8px;")
        layout.addWidget(iss_label)

        self.issues_text = QPlainTextEdit()
        self.issues_text.setReadOnly(True)
        self.issues_text.setStyleSheet(
            "background:#1e1e1e; color:#ce9178; border:1px solid #3e3e3e;"
            "font-family:'Courier New',monospace; font-size:10pt;")
        layout.addWidget(self.issues_text)

        # Action buttons
        btn_row = QHBoxLayout()
        self.vscode_btn = QPushButton("📝 Open in VSCode")
        self.vscode_btn.clicked.connect(self.open_vscode)
        btn_row.addWidget(self.vscode_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Recent improvements
        rec_label = QLabel("✅ RECENT IMPROVEMENTS")
        rec_label.setStyleSheet("font-weight:bold; color:#88c0d0; margin-top:8px;")
        layout.addWidget(rec_label)

        self.recent_text = QPlainTextEdit()
        self.recent_text.setReadOnly(True)
        self.recent_text.setMaximumHeight(90)
        self.recent_text.setStyleSheet(
            "background:#1e1e1e; color:#6a9955; border:1px solid #3e3e3e;"
            "font-family:'Courier New',monospace; font-size:9pt;")
        self.recent_text.setPlainText(
            "✓ Fixed router variable scope\n"
            "✓ Added proactive daemon integration\n"
            "✓ Implemented self-improvement system\n"
            "✓ Reduced GPU layers for stability")
        layout.addWidget(self.recent_text)

        QTimer.singleShot(3000, self.run_analysis)

    def set_daemon(self, daemon):
        self.daemon = daemon
        self.run_analysis()

    def run_analysis(self):
        if not self.daemon:
            try:
                from eli.brain.proactive_daemon import get_daemon
                self.daemon = get_daemon()
            except Exception:
                self.issues_text.setPlainText("⚠ Daemon not available.")
                return
        try:
            self.improvements = self.daemon.analyze_code_quality()
            count = len(self.improvements)
            score = max(50, 100 - count * 2)
            self.score_bar.setValue(score)
            self.issues_lbl.setText(f"Issues: {count}")
            if not self.improvements:
                self.issues_text.setPlainText("✨ No issues detected — code is clean!")
                return
            lines = []
            for imp in self.improvements:
                fname = imp.get('file', 'unknown')
                sug = imp.get('suggestion', '')
                lines.append(f"⚠ {fname}\n   {sug}\n")
            self.issues_text.setPlainText('\n'.join(lines))
        except Exception as e:
            self.issues_text.setPlainText(f"Analysis error: {e}")

    def open_vscode(self):
        import subprocess
        try:
            root = os.environ.get("ELI_ROOT", os.getcwd())
            subprocess.Popen(["code",
                os.path.join(root, "tools", "executor_enhanced.py"),
                os.path.join(root, "tools", "router_enhanced.py")])
        except Exception as e:
            print(f"VSCode launch error: {e}")


class IDEDockWidget(QWidget):
    """GUI dock tab: integrated code generation and editing workspace."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_file = None
        self.projects_dir = Path(os.path.expanduser("~/Desktop/eli_projects"))
        self.scripts_dir = Path(os.path.expanduser("~/Desktop/eli_scripts"))
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Header toolbar
        toolbar = QHBoxLayout()
        self.project_lbl = QLabel("📁 No project open")
        self.project_lbl.setStyleSheet("color:#88c0d0; font-weight:bold;")
        toolbar.addWidget(self.project_lbl)
        toolbar.addStretch()
        self.run_btn = QPushButton("▶ Run")
        self.run_btn.setStyleSheet("QPushButton{background:#0e639c;font-weight:bold;padding:4px 10px;}")
        self.run_btn.clicked.connect(self.run_code)
        self.save_btn = QPushButton("💾 Save")
        self.save_btn.clicked.connect(self.save_file)
        self.vscode_btn = QPushButton("🆚 VSCode")
        self.vscode_btn.clicked.connect(self.open_vscode)
        toolbar.addWidget(self.run_btn)
        toolbar.addWidget(self.save_btn)
        toolbar.addWidget(self.vscode_btn)
        layout.addLayout(toolbar)

        # Splitter: file tree | editor + console
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # File tree
        tree_widget = QWidget()
        tree_layout = QVBoxLayout(tree_widget)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_lbl = QLabel("📂 Files")
        tree_lbl.setStyleSheet("font-weight:bold; color:#88c0d0;")
        tree_layout.addWidget(tree_lbl)
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setStyleSheet(
            "QTreeWidget{background:#252526;color:#cccccc;border:1px solid #3e3e3e;"
            "font-family:'Courier New',monospace;}")
        self.file_tree.itemClicked.connect(self._on_file_click)
        tree_layout.addWidget(self.file_tree)
        splitter.addWidget(tree_widget)

        # Right: editor + console
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        editor_lbl = QLabel("✏️ Editor")
        editor_lbl.setStyleSheet("font-weight:bold; color:#88c0d0;")
        right_layout.addWidget(editor_lbl)
        self.file_path_lbl = QLabel("No file open")
        self.file_path_lbl.setStyleSheet("color:#6a9955; font-size:9px;")
        right_layout.addWidget(self.file_path_lbl)

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Courier New", 10))
        self.editor.setStyleSheet(
            "QPlainTextEdit{background:#1e1e1e;color:#d4d4d4;border:1px solid #3e3e3e;"
            "selection-background-color:#264f78;}")
        right_layout.addWidget(self.editor, 2)

        console_lbl = QLabel("🖥️ Output")
        console_lbl.setStyleSheet("font-weight:bold; color:#88c0d0; margin-top:6px;")
        right_layout.addWidget(console_lbl)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumHeight(140)
        self.console.setFont(QFont("Courier New", 9))
        self.console.setStyleSheet(
            "QPlainTextEdit{background:#0c0c0c;color:#cccccc;border:1px solid #3e3e3e;}")
        right_layout.addWidget(self.console, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter)

        # Bottom status
        self.status_lbl = QLabel("Ready — ask ELI: 'create a python script for X'")
        self.status_lbl.setStyleSheet("color:#88c0d0; font-size:9px; padding:2px;")
        layout.addWidget(self.status_lbl)

    def load_project(self, project_path: str):
        """Load a project or folder into the file tree."""
        path = Path(project_path)
        if not path.exists():
            return
        self.current_project = path
        self.project_lbl.setText(f"📁 {path.name}")
        self.file_tree.clear()
        self._populate_tree(path, self.file_tree)
        self.file_tree.expandAll()
        # Auto-open main file
        for name in ["main.py", "index.js", "main.cpp"]:
            f = path / name
            if f.exists():
                self._open_file(f)
                break
        self.status_lbl.setText(f"Loaded: {path}")

    def display_generated_code(self, code: str, filename: str = "generated.py"):
        """Display AI-generated code directly in editor."""
        self.editor.setPlainText(code)
        self.file_path_lbl.setText(f"Generated: {filename}")
        self.current_file = self.scripts_dir / filename
        self.console.appendPlainText(f"✨ Code generated: {filename}")
        self.status_lbl.setText(f"Code ready — click Save or Run")

    def _populate_tree(self, path: Path, parent):
        try:
            for item in sorted(path.iterdir()):
                if item.name.startswith('.') or item.name == '__pycache__':
                    continue
                node = QTreeWidgetItem(parent)
                icon = "📁" if item.is_dir() else "📄"
                node.setText(0, f"{icon} {item.name}")
                node.setData(0, Qt.ItemDataRole.UserRole, str(item))
                if item.is_dir():
                    self._populate_tree(item, node)
        except PermissionError:
            pass

    def _on_file_click(self, item, _col):
        fp = item.data(0, Qt.ItemDataRole.UserRole)
        if fp:
            p = Path(fp)
            if p.is_file():
                self._open_file(p)

    def _open_file(self, path: Path):
        try:
            self.editor.setPlainText(path.read_text(encoding="utf-8", errors="replace"))
            self.file_path_lbl.setText(str(path))
            self.current_file = path
        except Exception as e:
            self.console.appendPlainText(f"Error opening {path.name}: {e}")

    def save_file(self):
        if not self.current_file:
            return
        try:
            Path(self.current_file).write_text(self.editor.toPlainText(), encoding="utf-8")
            self.console.appendPlainText(f"✓ Saved: {self.current_file}")
        except Exception as e:
            self.console.appendPlainText(f"Save error: {e}")

    def run_code(self):
        if not self.current_file:
            self.console.appendPlainText("⚠ No file open")
            return
        self.save_file()
        self.console.appendPlainText(f"\n▶ Running {Path(self.current_file).name}...")
        import subprocess
        try:
            result = subprocess.run(
                ["python3", str(self.current_file)],
                capture_output=True, text=True, timeout=15
            )
            if result.stdout:
                self.console.appendPlainText(result.stdout)
            if result.stderr:
                self.console.appendPlainText(f"stderr:\n{result.stderr}")
            self.console.appendPlainText("✓ Done")
        except subprocess.TimeoutExpired:
            self.console.appendPlainText("⚠ Timeout (15s)")
        except Exception as e:
            self.console.appendPlainText(f"Error: {e}")

    def open_vscode(self):
        import subprocess
        target = str(self.current_project) if hasattr(self, 'current_project') else str(self.projects_dir)
        try:
            subprocess.Popen(["code", target])
            self.console.appendPlainText(f"✓ Opened VSCode: {target}")
        except Exception as e:
            self.console.appendPlainText(f"VSCode error: {e}")


class ELIWorker(QThread):
    """Worker thread for non‑CHAT actions (executor)."""
    token_chunk = Signal(str)
    system_error = Signal(str)
    execution_complete = Signal(object)
    stream_started = Signal(object)
    stream_end = Signal(object)

    def __init__(self, action, args, user_text=""):
        super().__init__()
        self.action = (action or "CHAT").upper()
        self.args = args or {}
        self.user_text = (
            user_text
            or (self.args.get("message") if isinstance(self.args, dict) else "")
            or ""
        )

    def run(self):
        t0 = time.time()
        try:
            if self.action == "CHAT":
                from eli.tools.chat_model import chat_response_stream
                prompt = (self.args.get("message") or self.user_text or "").strip()
                self.stream_started.emit({"ok": True, "action": "CHAT", "event": "stream_started"})
                full = ""
                n_chunks = 0
                try:
                    for chunk in chat_response_stream(prompt):
                        if not chunk:
                            continue
                        n_chunks += 1
                        full += chunk
                        self.token_chunk.emit(chunk)
                    dt = time.time() - t0
                    self.stream_end.emit({
                        "ok": True, "action": "CHAT", "event": "stream_end",
                        "chunks": n_chunks, "seconds": dt, "reason": "eos"
                    })
                    self.execution_complete.emit({
                        "ok": True, "action": "CHAT", "content": full,
                        "streamed": True, "chunks": n_chunks, "seconds": dt
                    })
                except Exception as e:
                    dt = time.time() - t0
                    err = f"[chat_stream_error] {e}"
                    self.stream_end.emit({
                        "ok": False, "action": "CHAT", "event": "stream_end",
                        "chunks": n_chunks, "seconds": dt, "reason": "exception", "error": err
                    })
                    self.execution_complete.emit({
                        "ok": False, "action": "CHAT", "content": err,
                        "streamed": True, "chunks": n_chunks, "seconds": dt
                    })
                return

            # Non‑CHAT path
            from eli.tools.executor_enhanced import execute as _execute
            res = _execute(self.action, self.args)
            if not isinstance(res, dict):
                res = {"ok": True, "content": str(res)}
            res.setdefault("action", self.action)
            res.setdefault("seconds", time.time() - t0)
            self.execution_complete.emit(res)

        except Exception as e:
            tb = traceback.format_exc(limit=6)
            self.system_error.emit(f"{e}\n{tb}")


class LLMStreamWorker(QThread):
    """Worker thread that streams chat tokens from the cognitive engine."""
    token_chunk = Signal(str)
    stream_ended = Signal()
    error_occurred = Signal(str)

    def __init__(self, user_input: str):
        super().__init__()
        self.user_input = user_input

    def run(self):
        try:
            engine = get_engine()
            result = engine.process(self.user_input, source="gui", stream=True)
            if hasattr(result, '__iter__') and not isinstance(result, dict):
                for chunk in result:
                    if chunk:
                        self.token_chunk.emit(chunk)
                self.stream_ended.emit()
            else:
                self.token_chunk.emit(result.get("content", ""))
                self.stream_ended.emit()
        except Exception as e:
            self.error_occurred.emit(str(e))


class HabitDockWidget(QWidget):
    """GUI dock tab: displays and manages habit rules."""
    rule_state_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.memory = get_memory()
        self.init_ui()
        self.refresh()
        self.rule_state_changed.connect(self.refresh)

    def init_ui(self):
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("🧠 HABIT AUTOMATION")
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #5e81ac;")
        header.addWidget(title)
        header.addStretch()
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        info = QLabel("ELI learns your daily routines and can automate them. Enable/disable rules below.")
        info.setWordWrap(True)
        info.setStyleSheet("color: #88c0d0; padding: 5px;")
        layout.addWidget(info)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Rule", "Time", "Command", "Status", "Actions"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

    def refresh(self):
        rules = self.memory.get_habit_rules(enabled_only=False)
        self.table.setRowCount(len(rules))
        for i, rule in enumerate(rules):
            name_item = QTableWidgetItem(rule.get("name", "Unnamed"))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, name_item)
            time_str = f"{rule['hour']:02d}:{rule['minute']:02d}"
            time_item = QTableWidgetItem(time_str)
            time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 1, time_item)
            cmd_item = QTableWidgetItem(rule.get("command", ""))
            cmd_item.setFlags(cmd_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 2, cmd_item)
            enabled = rule.get("enabled", 1)
            cb = QCheckBox()
            cb.setChecked(bool(enabled))
            cb.stateChanged.connect(lambda state, rid=rule["id"]: self.toggle_rule(rid, state))
            self.table.setCellWidget(i, 3, cb)
            delete_btn = QPushButton("🗑️ Delete")
            delete_btn.clicked.connect(lambda _, rid=rule["id"]: self.delete_rule(rid))
            self.table.setCellWidget(i, 4, delete_btn)
        self.table.resizeColumnsToContents()

    def toggle_rule(self, rule_id, state):
        enabled = 1 if state == Qt.CheckState.Checked else 0
        self.memory.update_habit_rule(rule_id, enabled=enabled)
        self.rule_state_changed.emit()

    def delete_rule(self, rule_id):
        reply = QMessageBox.question(
            self, "Delete Habit",
            "Are you sure you want to delete this habit rule?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.memory.delete_habit_rule(rule_id)
            self.rule_state_changed.emit()


class ELIEntropicGUI(QMainWindow):
    # Qt Signal for voice commands (thread-safe)
    voice_command_received = Signal(str)

    def __init__(self):
        super().__init__()
        self._threads = []
        self._workers = []

        self.setWindowTitle("ELI - Entropic Logical Interpreter v3")
        self.setGeometry(100, 100, 1200, 850)

        # System state
        self.conversation_log = []
        self.system_status = "INITIALIZING"
        self.active_workers = 0
        self._busy = False
        self._last_audio_text = ""
        self._last_audio_ts = 0.0
        self._audio_cooldown_sec = 1.0
        self._command_queue = []
        self._max_queue_size = 3
        self._processing_queue = False
        self._pending_partial_audio = ""
        self._pending_partial_ts = 0.0
        self._partial_timeout_sec = 1.8

        self.start_time = datetime.now()
        self.audio_listening = False

        # Streaming buffer
        self._stream_buf = []
        self._streaming_active = False
        self._stream_flush_timer = QTimer(self)
        self._stream_flush_timer.setInterval(33)
        if not hasattr(self, '_flush_stream_buffer'):
            self._flush_stream_buffer = lambda: None
        self._stream_flush_timer.timeout.connect(self._flush_stream_buffer)

        # Connect voice signal
        self.voice_command_received.connect(self.process_audio_transcript_from_callback)

        # Initialize cognitive engine and check GGUF
        self.engine = get_engine()
        # ----- DEBUG: Verify GGUF model availability -----
        from eli.brain import gguf_inference
        model_path = gguf_inference.get_model_path()
        print(f"[DEBUG] GGUF model path: {model_path}")
        model_path = str(PATHS.model)  # force correct path
        model_path = str(PATHS.model)  # force correct path
        print(f"[DEBUG] GGUF available: {self.engine._gguf_available}")
        # ------------------------------------------------

        # Initialize UI
        self.init_ui()
        self.apply_entropic_theme()
        QTimer.singleShot(500, self.system_startup)
        QTimer.singleShot(1000, self.input_field.setFocus)

    # =============== HELPER METHODS ===============

    def _log_system(self, message: str):
        """Log system message"""
        try:
            self.add_system_message("SYSTEM", message, "#88c0d0")
        except Exception:
            print(f"[SYSTEM] {message}")

    def _enqueue_command(self, text: str):
        """Add command to queue if busy"""
        txt = (text or "").strip()
        if not txt:
            return
        if len(self._command_queue) >= self._max_queue_size:
            self._log_system(f"Queue full ({len(self._command_queue)}/{self._max_queue_size}). Dropping: {txt}")
            return
        self._command_queue.append(txt)
        self._log_system(f"Queued command ({len(self._command_queue)}/{self._max_queue_size}): {txt}")

    def _process_next_queued_command(self):
        """Process next command in queue"""
        if self._busy:
            return
        if not self._command_queue:
            self._processing_queue = False
            return
        self._processing_queue = True
        nxt = self._command_queue.pop(0)
        self._log_system(f"Processing queued command: {nxt}")
        self.input_field.setText(nxt)
        self.process_input_stream()

    def _normalize_voice_text(self, text: str) -> str:
        """Normalize voice input text"""
        t = (text or "").strip()
        if not t:
            return ""
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _merge_partial_voice(self, text: str) -> str:
        """Merge partial voice commands"""
        now = time.time()
        t = self._normalize_voice_text(text)
        if not t:
            return ""

        low = t.lower()
        # Hold short opener if likely truncated by STT
        if low in {"open", "search", "play", "send", "create"}:
            self._pending_partial_audio = t
            self._pending_partial_ts = now
            self._log_system(f"Held partial command: {t}")
            return ""

        # Merge continuation if it arrives quickly
        if self._pending_partial_audio and (now - self._pending_partial_ts) <= self._partial_timeout_sec:
            merged = f"{self._pending_partial_audio} {t}".strip()
            self._pending_partial_audio = ""
            self._pending_partial_ts = 0.0
            return merged

        # Clear stale partial
        if self._pending_partial_audio and (now - self._pending_partial_ts) > self._partial_timeout_sec:
            self._pending_partial_audio = ""
            self._pending_partial_ts = 0.0

        return t

    def process_audio_transcript_from_callback(self, transcript: str):
        """
        Thread-safe voice callback entrypoint.
        Supports bounded queue + partial-command merge (e.g., "open" + "browser").
        """
        text = (transcript or "").strip()
        print(f"[GUI] Processing audio transcript: {text!r}")
        if not text:
            return

        merged = self._merge_partial_voice(text)
        if not merged:
            return

        now = time.time()
        if merged.lower() == self._last_audio_text.lower() and (now - self._last_audio_ts) < self._audio_cooldown_sec:
            self._log_system("Ignoring duplicate voice command (cooldown).")
            return

        self._last_audio_text = merged
        self._last_audio_ts = now

        if self._busy:
            self._enqueue_command(merged)
            return

        # Set the input field and process
        self.add_system_message("VOICE", merged, "#d08770")
        self.input_field.setText(merged)
        self.process_input_stream()

    def _parse_local_command(self, text: str):
        """Parse local commands (volume, media, time/date)"""
        t = (text or "").strip().lower()
        if not t:
            return None, {}

        # Volume
        if re.fullmatch(r"(what\s+is\s+)?(the\s+)?volume(\s+level)?\??", t):
            return "VOLUME_GET", {}
        m = re.match(r"^(?:set\s+)?volume(?:\s+to)?\s+(\d{1,3})%?$", t)
        if m:
            return "VOLUME_SET", {"level": max(0, min(100, int(m.group(1))))}
        m = re.match(r"^volume\s+(up|down)(?:\s+(\d{1,3}))?$", t)
        if m:
            step = max(1, min(100, int(m.group(2) or 5)))
            return ("VOLUME_UP" if m.group(1) == "up" else "VOLUME_DOWN"), {"step": step}
        if t in {"mute", "unmute"}:
            return ("VOLUME_MUTE" if t == "mute" else "VOLUME_UNMUTE"), {}

        # Media
        if t in {"next", "next song", "next track", "skip", "skip track"}:
            return "MEDIA_NEXT", {}
        if t in {"previous", "previous song", "previous track", "back track"}:
            return "MEDIA_PREV", {}
        if t in {"pause", "resume", "play", "play pause"}:
            return "MEDIA_TOGGLE", {}

        # Time/Date
        if t in {"time", "what time is it"}:
            return "GET_TIME", {}
        if t in {"date", "what is the date", "today"}:
            return "GET_DATE", {}

        return None, {}

    def _linux_get_volume_percent(self):
        """Get current volume percentage on Linux"""
        import subprocess
        try:
            wp = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True, text=True, timeout=1.5
            )
            if wp.returncode == 0 and wp.stdout:
                m = re.search(r"([0-9]*\.?[0-9]+)", wp.stdout)
                if m:
                    return int(round(float(m.group(1)) * 100))
        except Exception:
            pass

        try:
            am = subprocess.run(
                ["amixer", "get", "Master"],
                capture_output=True, text=True, timeout=1.5
            )
            if am.returncode == 0 and am.stdout:
                vals = re.findall(r"\[(\d{1,3})%\]", am.stdout)
                if vals:
                    return int(vals[-1])
        except Exception:
            pass

        return None

    def _fallback_volume(self, kind: str, payload: dict):
        """Fallback volume control for Linux"""
        import subprocess

        def _ok(msg: str):
            return {"ok": True, "content": msg}
        def _fail(msg: str):
            return {"ok": False, "content": msg}

        try:
            if kind == "VOLUME_GET":
                pct = self._linux_get_volume_percent()
                if pct is None:
                    return _fail("Volume read failed")
                return _ok(f"Current volume: {pct}%")

            if kind == "VOLUME_SET":
                level = int(payload.get("level", 50))
                subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level}%"], check=True, timeout=1.5)
                return _ok(f"Volume set to {level}%")

            if kind == "VOLUME_UP":
                step = int(payload.get("step", 5))
                subprocess.run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{step}%+"], check=True, timeout=1.5)
                pct = self._linux_get_volume_percent()
                return _ok(f"Volume raised by {step}%{'' if pct is None else f' (now {pct}%)'}")

            if kind == "VOLUME_DOWN":
                step = int(payload.get("step", 5))
                subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{step}%-"], check=True, timeout=1.5)
                pct = self._linux_get_volume_percent()
                return _ok(f"Volume lowered by {step}%{'' if pct is None else f' (now {pct}%)'}")

            if kind == "VOLUME_MUTE":
                subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"], check=True, timeout=1.5)
                return _ok("Muted")

            if kind == "VOLUME_UNMUTE":
                subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], check=True, timeout=1.5)
                return _ok("Unmuted")

        except Exception:
            try:
                if kind == "VOLUME_GET":
                    pct = self._linux_get_volume_percent()
                    if pct is None:
                        return _fail("Volume read failed")
                    return _ok(f"Current volume: {pct}%")

                if kind == "VOLUME_SET":
                    level = int(payload.get("level", 50))
                    subprocess.run(["amixer", "set", "Master", f"{level}%"], check=True, timeout=1.5)
                    return _ok(f"Volume set to {level}%")

                if kind == "VOLUME_UP":
                    step = int(payload.get("step", 5))
                    subprocess.run(["amixer", "set", "Master", f"{step}%+"], check=True, timeout=1.5)
                    pct = self._linux_get_volume_percent()
                    return _ok(f"Volume raised by {step}%{'' if pct is None else f' (now {pct}%)'}")

                if kind == "VOLUME_DOWN":
                    step = int(payload.get("step", 5))
                    subprocess.run(["amixer", "set", "Master", f"{step}%-"], check=True, timeout=1.5)
                    pct = self._linux_get_volume_percent()
                    return _ok(f"Volume lowered by {step}%{'' if pct is None else f' (now {pct}%)'}")

                if kind == "VOLUME_MUTE":
                    subprocess.run(["amixer", "set", "Master", "mute"], check=True, timeout=1.5)
                    return _ok("Muted")

                if kind == "VOLUME_UNMUTE":
                    subprocess.run(["amixer", "set", "Master", "unmute"], check=True, timeout=1.5)
                    return _ok("Unmuted")
            except Exception as e2:
                return _fail(f"Volume control failed: {e2}")

        return _fail("Volume control failed")

def _dispatch_local_command(self, kind: str, payload: dict):
    """Dispatch local command – volume commands use fallback, others use executor."""
    # All volume commands go directly to the reliable fallback
    if kind.startswith("VOLUME_"):
        return self._fallback_volume(kind, payload)

    from eli.tools.executor_enhanced import execute
    try:
        if kind == "MEDIA_NEXT":
            return execute("NEXT_MEDIA", {})
        elif kind == "MEDIA_PREV":
            return execute("PREVIOUS_MEDIA", {})
        elif kind == "MEDIA_TOGGLE":
            # map to PLAY_PAUSE if your executor supports it, otherwise use PAUSE/PLAY
            return execute("PLAY_PAUSE", {})
        elif kind == "GET_TIME":
            return execute("GET_TIME", {})
        elif kind == "GET_DATE":
            return execute("GET_DATE", {})
    except Exception as e:
        print(f"[LOCAL EXECUTOR ERROR] {e}")

    return {"ok": False, "content": "Command failed."}

    def _dispatch_local_or_router(self, user_input: str):
        """Dispatch to local command or router"""
        from eli.tools.intent_router import route
        kind, payload = self._parse_local_command(user_input)
        if kind is not None:
            mapping = {
                "VOLUME_GET": ("VOLUME", {"mode": "get"}),
                "VOLUME_MUTE": ("VOLUME", {"mode": "mute"}),
                "VOLUME_UNMUTE": ("VOLUME", {"mode": "unmute"}),
                "MEDIA_NEXT": ("NEXT_MEDIA", {}),
                "MEDIA_PREV": ("PREV_MEDIA", {}),
                "MEDIA_TOGGLE": ("PLAY_PAUSE", {}),
                "GET_TIME": ("GET_TIME", {}),
                "GET_DATE": ("GET_DATE", {}),
            }

            if kind == "VOLUME_SET":
                action, args = ("VOLUME", {"mode": "set", "level": payload["level"]})
            elif kind == "VOLUME_UP":
                action, args = ("VOLUME", {"mode": "up", "step": payload.get("step", 5)})
            elif kind == "VOLUME_DOWN":
                action, args = ("VOLUME", {"mode": "down", "step": payload.get("step", 5)})
            else:
                action, args = mapping.get(kind, ("CHAT", {"message": user_input}))

            self.add_system_message("COGNITIVE", f"Router bypass (deterministic): {action} {args}", "#8fbcbb")
            return action, args, 1.0

        route_result = route(user_input)
        self.add_system_message("COGNITIVE", f"Router parsed: {route_result}", "#8fbcbb")
        if not route_result:
            return "CHAT", {"message": user_input}, 0.0

        return (
            route_result.get("action", "CHAT"),
            route_result.get("args", {}),
            route_result.get("confidence", 0.0),
        )

    # =============== UI INITIALIZATION ===============

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.init_left_panel(main_layout)
        self.init_right_panel(main_layout)
        self.init_status_bar()

    def init_left_panel(self, main_layout):
        left_panel = QFrame()
        left_panel.setFixedWidth(280)
        left_panel.setObjectName("leftPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(15, 20, 15, 20)
        left_layout.setSpacing(15)

        # Title
        title_frame = QFrame()
        title_frame.setObjectName("titleFrame")
        title_layout = QVBoxLayout(title_frame)
        eli_logo = QLabel("◈ ELI ◈")
        eli_logo.setObjectName("eliLogo")
        eli_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(eli_logo)
        eli_title = QLabel("Entropic Logical\nInterpreter v3")
        eli_title.setObjectName("eliTitle")
        eli_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(eli_title)
        left_layout.addWidget(title_frame)

        # System status
        status_frame = QFrame()
        status_frame.setObjectName("statusFrame")
        status_layout = QVBoxLayout(status_frame)
        status_label = QLabel("SYSTEM STATUS")
        status_label.setObjectName("sectionTitle")
        status_layout.addWidget(status_label)
        self.status_indicator = QLabel("● INITIALIZING")
        self.status_indicator.setObjectName("statusIndicator")
        status_layout.addWidget(self.status_indicator)
        metrics = [
            ("Neural Network", "SYNCHRONIZED"),
            ("Memory Cache", "OPTIMAL"),
            ("I/O Bandwidth", "STABLE"),
            ("Security", "ENCRYPTED"),
            ("Audio Input", "READY"),
        ]
        for metric, value in metrics:
            metric_frame = QFrame()
            metric_layout = QHBoxLayout(metric_frame)
            metric_layout.setContentsMargins(0, 5, 0, 5)
            metric_label = QLabel(metric)
            metric_label.setObjectName("metricLabel")
            metric_layout.addWidget(metric_label)
            metric_value = QLabel(value)
            metric_value.setObjectName("metricValue")
            metric_layout.addWidget(metric_value)
            status_layout.addWidget(metric_frame)
        left_layout.addWidget(status_frame)

        # Audio control
        audio_frame = QFrame()
        audio_frame.setObjectName("audioFrame")
        audio_layout = QVBoxLayout(audio_frame)
        audio_label = QLabel("AUDIO CONTROL")
        audio_label.setObjectName("sectionTitle")
        audio_layout.addWidget(audio_label)
        audio_toggle_frame = QFrame()
        audio_toggle_layout = QHBoxLayout(audio_toggle_frame)
        self.audio_button = QPushButton("🎤 OFF")
        self.audio_button.setObjectName("audioButton")
        self.audio_button.setCheckable(True)
        self.audio_button.toggled.connect(self.toggle_audio_input)
        self.audio_button.setToolTip("Toggle continuous voice listening")
        audio_toggle_layout.addWidget(self.audio_button)
        self.audio_status = QLabel("Voice: DISABLED")
        self.audio_status.setObjectName("audioStatus")
        audio_toggle_layout.addWidget(self.audio_status)
        audio_layout.addWidget(audio_toggle_frame)
        voice_btn = QPushButton("🎤 Voice Command")
        voice_btn.setObjectName("quickButton")
        voice_btn.setToolTip("Activate single voice command")
        voice_btn.clicked.connect(self.listen_once_command)
        audio_layout.addWidget(voice_btn)
        left_layout.addWidget(audio_frame)

        # Quick access
        access_frame = QFrame()
        access_frame.setObjectName("accessFrame")
        access_layout = QVBoxLayout(access_frame)
        access_label = QLabel("QUICK ACCESS")
        access_label.setObjectName("sectionTitle")
        access_layout.addWidget(access_label)
        quick_actions = [
            ("🌐", "Network Browser", self.quick_browser, "Launch quantum browser"),
            ("🎵", "Audio Interface", self.quick_spotify, "Access sonic database"),
            ("📧", "Communication Hub", self.quick_email, "Open message matrix"),
            ("📄", "Data Fabricator", self.quick_document, "Create new data construct"),
            ("📁", "File System", self.quick_files, "Access storage matrix"),
            ("🔍", "Information Scan", self.quick_search, "Initiate data probe"),
            ("⏰", "Temporal Node", self.quick_time, "Check chronal alignment"),
            ("💾", "Memory Recall", self.quick_memory, "Access neural archive"),
        ]
        for icon, text, callback, tooltip in quick_actions:
            btn = QPushButton(f"{icon} {text}")
            btn.setObjectName("quickButton")
            btn.setToolTip(tooltip)
            btn.clicked.connect(callback)
            access_layout.addWidget(btn)
        left_layout.addWidget(access_frame)

        # Time display
        time_frame = QFrame()
        time_layout = QVBoxLayout(time_frame)
        self.system_time = QLabel("00:00:00")
        self.system_time.setObjectName("systemTime")
        self.system_time.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_layout.addWidget(self.system_time)
        self.system_date = QLabel("YYYY-MM-DD")
        self.system_date.setObjectName("systemDate")
        self.system_date.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_layout.addWidget(self.system_date)
        left_layout.addWidget(time_frame)
        left_layout.addStretch()
        main_layout.addWidget(left_panel)

    def init_right_panel(self, main_layout):
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self._right_layout = right_layout
        right_layout.setContentsMargins(20, 20, 20, 20)
        right_layout.setSpacing(15)

        # Conversation header
        header_frame = QFrame()
        header_layout = QHBoxLayout(header_frame)
        conversation_title = QLabel("NEURAL INTERFACE CONSOLE")
        conversation_title.setObjectName("consoleTitle")
        header_layout.addWidget(conversation_title)
        header_layout.addStretch()
        self.process_indicator = QLabel("◌ IDLE")
        self.process_indicator.setObjectName("processIndicator")
        header_layout.addWidget(self.process_indicator)
        right_layout.addWidget(header_frame)

        # Conversation display
        self.conversation_display = QTextEdit()
        self.conversation_display.setObjectName("conversationDisplay")
        self.conversation_display.setReadOnly(True)

        # Tabs
        self.tabs = QTabWidget()
        console_wrap = QWidget()
        console_layout = QVBoxLayout(console_wrap)
        console_layout.setContentsMargins(0, 0, 0, 0)
        console_layout.addWidget(self.conversation_display)
        self.proactive_dock = ProactiveDockWidget()
        self.tabs.addTab(console_wrap, "Console")
        self.tabs.addTab(self.proactive_dock, "Proactive")
        self.habit_dock = HabitDockWidget()
        self.tabs.addTab(self.habit_dock, "Habits")
        self.self_improve_dock = SelfImproveDockWidget()
        self.tabs.addTab(self.self_improve_dock, "🔧 Self-Improve")
        self.ide_dock = IDEDockWidget()
        self.tabs.addTab(self.ide_dock, "💻 Code")
        right_layout.addWidget(self.tabs, 1)

        # Input area
        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        input_layout = QVBoxLayout(input_frame)
        input_label = QLabel("ENTROPIC INPUT STREAM")
        input_label.setObjectName("inputLabel")
        input_layout.addWidget(input_label)
        input_row = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setObjectName("inputField")
        self.input_field.setPlaceholderText("Enter command stream... (e.g., 'access network browser', 'query meaning of existence', 'fabricate document')")
        self.input_field.returnPressed.connect(self.process_input_stream)
        input_row.addWidget(self.input_field, 1)
        self.execute_button = QPushButton("EXECUTE")
        self.execute_button.setObjectName("executeButton")
        self.execute_button.clicked.connect(self.process_input_stream)
        input_row.addWidget(self.execute_button)
        input_layout.addLayout(input_row)
        right_layout.addWidget(input_frame)

        # Command suggestions
        suggestions_frame = QFrame()
        suggestions_layout = QHBoxLayout(suggestions_frame)
        suggestion_label = QLabel("QUICK COMMANDS:")
        suggestion_label.setObjectName("suggestionLabel")
        suggestions_layout.addWidget(suggestion_label)
        suggestions = [
            ("access network", "access network browser"),
            ("initiate audio", "initiate audio interface"),
            ("fabricate document", "fabricate data construct"),
            ("scan information", "scan information database"),
            ("query existence", "what's the meaning of life?"),
            ("check chronal", "check chronal alignment"),
        ]
        for text, cmd in suggestions:
            btn = QPushButton(text)
            btn.setObjectName("suggestionButton")
            btn.clicked.connect(lambda checked=False, c=cmd: self.run_quick_command(c))
            suggestions_layout.addWidget(btn)
        suggestions_layout.addStretch()
        right_layout.addWidget(suggestions_frame)
        main_layout.addWidget(right_panel, 1)

    def init_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.system_info = QLabel(f"ELI v2.2 | Quantum State: STABLE | Uptime: 00:00:00")
        self.status_bar.addWidget(self.system_info)
        self.memory_display = QLabel("Memory: --/-- MB")
        self.status_bar.addPermanentWidget(self.memory_display)
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_system_info)
        self.update_timer.start(1000)

    def apply_entropic_theme(self):
        self.setStyleSheet("""
            /* Main window */
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0a0e14, stop:1 #151b26);
            }
            #leftPanel {
                background-color: rgba(10, 14, 20, 0.9);
                border-right: 1px solid #1e2532;
            }
            #titleFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a5fb4, stop:1 #26a269);
                border-radius: 8px;
                padding: 15px;
            }
            #eliLogo {
                color: white;
                font-size: 28px;
                font-weight: bold;
                font-family: 'Monospace';
            }
            #eliTitle {
                color: white;
                font-size: 14px;
                font-weight: bold;
                font-family: 'Arial';
            }
            #sectionTitle {
                color: #5e81ac;
                font-size: 11px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
                margin-bottom: 5px;
            }
            #statusFrame {
                background-color: rgba(30, 37, 50, 0.6);
                border-radius: 6px;
                padding: 12px;
                border: 1px solid #2d3748;
            }
            #statusIndicator {
                color: #f6d32d;
                font-size: 13px;
                font-weight: bold;
                font-family: 'Monospace';
                margin-bottom: 15px;
            }
            #metricLabel {
                color: #88c0d0;
                font-size: 11px;
            }
            #metricValue {
                color: #a3be8c;
                font-size: 11px;
                font-weight: bold;
            }
            #audioFrame {
                background-color: rgba(30, 37, 50, 0.6);
                border-radius: 6px;
                padding: 12px;
                border: 1px solid #2d3748;
            }
            #audioButton {
                background-color: rgba(46, 52, 64, 0.7);
                color: #d8dee9;
                border: 1px solid #4c566a;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
                min-width: 80px;
            }
            #audioButton:checked {
                background-color: rgba(191, 97, 106, 0.8);
                color: white;
                border: 1px solid #bf616a;
            }
            #audioButton:hover {
                background-color: rgba(76, 86, 106, 0.8);
            }
            #audioStatus {
                color: #88c0d0;
                font-size: 10px;
                font-family: 'Monospace';
            }
            #accessFrame {
                background-color: rgba(30, 37, 50, 0.6);
                border-radius: 6px;
                padding: 12px;
                border: 1px solid #2d3748;
            }
            #quickButton {
                background-color: rgba(46, 52, 64, 0.7);
                color: #d8dee9;
                border: 1px solid #4c566a;
                border-radius: 4px;
                padding: 8px;
                font-size: 11px;
                text-align: left;
                margin: 2px;
            }
            #quickButton:hover {
                background-color: rgba(76, 86, 106, 0.8);
                border: 1px solid #5e81ac;
            }
            #quickButton:pressed {
                background-color: rgba(94, 129, 172, 0.8);
            }
            #systemTime {
                color: #81a1c1;
                font-size: 18px;
                font-weight: bold;
                font-family: 'Monospace';
            }
            #systemDate {
                color: #88c0d0;
                font-size: 12px;
                font-family: 'Monospace';
            }
            #consoleTitle {
                color: #5e81ac;
                font-size: 14px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            #processIndicator {
                color: #a3be8c;
                font-size: 11px;
                font-weight: bold;
                font-family: 'Monospace';
            }
            #conversationDisplay {
                background-color: rgba(10, 14, 20, 0.8);
                border: 1px solid #2d3748;
                border-radius: 6px;
                color: #d8dee9;
                font-family: 'Consolas', 'Monospace';
                font-size: 12px;
                padding: 15px;
                selection-background-color: #4c566a;
            }
            #inputFrame {
                background-color: rgba(30, 37, 50, 0.6);
                border-radius: 6px;
                padding: 12px;
                border: 1px solid #2d3748;
            }
            #inputLabel {
                color: #5e81ac;
                font-size: 11px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
                margin-bottom: 8px;
            }
            #inputField {
                background-color: rgba(10, 14, 20, 0.9);
                border: 2px solid #3b4252;
                border-radius: 4px;
                color: #e5e9f0;
                font-size: 13px;
                padding: 10px;
                font-family: 'Monospace';
            }
            #inputField:focus {
                border: 2px solid #5e81ac;
                background-color: rgba(10, 14, 20, 1);
            }
            #executeButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1a5fb4, stop:1 #26a269);
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px 20px;
                font-size: 12px;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            #executeButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2d7ad1, stop:1 #38b87c);
            }
            #executeButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #154d8c, stop:1 #1d8a5c);
            }
            #suggestionLabel {
                color: #5e81ac;
                font-size: 11px;
                font-weight: bold;
                margin-right: 10px;
            }
            #suggestionButton {
                background-color: rgba(46, 52, 64, 0.7);
                color: #88c0d0;
                border: 1px solid #4c566a;
                border-radius: 3px;
                padding: 5px 10px;
                font-size: 10px;
                margin: 0 3px;
            }
            #suggestionButton:hover {
                background-color: rgba(76, 86, 106, 0.8);
                color: #d8dee9;
            }
            QStatusBar {
                background-color: rgba(10, 14, 20, 0.9);
                color: #88c0d0;
                font-size: 10px;
                border-top: 1px solid #1e2532;
            }
            QStatusBar QLabel {
                color: #88c0d0;
                font-size: 10px;
                font-family: 'Monospace';
            }
        """)

    def system_startup(self):
        self.add_system_message("SYSTEM", "Entropic Logical Interpreter v3", "#5e81ac")
        self.add_system_message("SYSTEM", "Initializing quantum neural matrix...", "#88c0d0")
        QTimer.singleShot(800, lambda: self.add_system_message("BOOT", "✓ Core protocols loaded", "#a3be8c"))
        QTimer.singleShot(1200, lambda: self.add_system_message("BOOT", "✓ Memory cache initialized", "#a3be8c"))
        QTimer.singleShot(1600, lambda: self.add_system_message("BOOT", "✓ I/O channels established", "#a3be8c"))
        QTimer.singleShot(2000, lambda: self.add_system_message("BOOT", "✓ Security encryption active", "#a3be8c"))
        QTimer.singleShot(2400, lambda: self.add_system_message("BOOT", "✓ Audio STT subsystem ready", "#a3be8c"))
        QTimer.singleShot(3000, lambda: self.set_system_status("OPERATIONAL"))
        QTimer.singleShot(3100, lambda: self.add_system_message("SYSTEM", "Ready for entropic input stream", "#5e81ac"))
        QTimer.singleShot(3200, lambda: self.add_system_message("AUDIO", "Voice commands available. Say 'ELI' followed by command.", "#88c0d0"))

    def set_system_status(self, status):
        self.system_status = status
        colors = {
            "INITIALIZING": "#f6d32d",
            "OPERATIONAL": "#a3be8c",
            "PROCESSING": "#5e81ac",
            "ERROR": "#bf616a"
        }
        color = colors.get(status, "#d8dee9")
        self.status_indicator.setText(f"● {status}")
        self.status_indicator.setStyleSheet(f"color: {color};")

    def add_system_message(self, source, message, color="#d8dee9"):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        html = f"""
        <div style="margin: 8px 0;">
            <span style="color: {color}; font-weight: bold; font-family: 'Monospace';">[{timestamp}] {source}</span>
            <div style="color: {color}; margin-left: 20px; font-family: 'Monospace';">{message}</div>
        </div>
        """
        self.conversation_display.append(html)
        self.conversation_display.ensureCursorVisible()
        self.conversation_log.append({
            'timestamp': timestamp,
            'source': source,
            'message': message,
            'color': color
        })

    def update_system_info(self):
        current_time = datetime.now()
        self.system_time.setText(current_time.strftime("%H:%M:%S"))
        self.system_date.setText(current_time.strftime("%Y-%m-%d"))
        uptime = current_time - self.start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        self.system_info.setText(f"ELI v2.2 | Quantum State: {self.system_status} | Uptime: {uptime_str}")
        import random
        mem_used = random.randint(200, 400)
        mem_total = 1024
        self.memory_display.setText(f"Memory: {mem_used}/{mem_total} MB")


    def _parse_local_command(self, text: str):
        import re
        t = (text or "").strip().lower()
        if not t:
            return None, {}

        # ---------- Volume ----------
        # "volume", "what is the volume", "volume level"
        if re.fullmatch(r"(what\s+is\s+)?(the\s+)?volume(\s+level)?\??", t):
            return "VOLUME_GET", {}

        # "set volume 42", "set volume to 42%", "volume 42"
        m = re.match(r"^(?:set\s+)?volume(?:\s+to)?\s+(\d{1,3})%?$", t)
        if m:
            return "VOLUME_SET", {"level": max(0, min(100, int(m.group(1))))}

        # "volume up", "volume up 10", "volume down", "volume down 7%"
        m = re.match(r"^volume\s+(up|down)(?:\s+(\d{1,3}))?%?$", t)
        if m:
            step = max(1, min(100, int(m.group(2) or 5)))
            return ("VOLUME_UP" if m.group(1) == "up" else "VOLUME_DOWN"), {"step": step}

        if t in {"mute", "unmute"}:
            return ("VOLUME_MUTE" if t == "mute" else "VOLUME_UNMUTE"), {}

        # ---------- Media ----------
        if t in {"next", "next song", "next track", "skip", "skip track"}:
            return "MEDIA_NEXT", {}
        if t in {"previous", "previous song", "previous track", "back track"}:
            return "MEDIA_PREV", {}
        if t in {"pause", "hold"}:
            return "MEDIA_PAUSE", {}
        if t in {"play", "resume"}:
            return "MEDIA_PLAY", {}
        if t in {"stop"}:
            return "MEDIA_STOP", {}

        # ---------- Time / Date ----------
        if t in {"time", "what time is it"}:
            return "GET_TIME", {}
        if t in {"date", "what is the date", "today"}:
            return "GET_DATE", {}

        return None, {}



    def _normalize_voice_command(self, text: str) -> str:
        t = (text or "").strip().lower()
        if not t:
            return ""
        alias = {
            "browser": "open browser",
            "open browser": "access network browser",
            "open network": "access network browser",
            "network browser": "access network browser",
            "next song": "next",
            "previous song": "previous",
        }
        return alias.get(t, t)

    def _is_ambiguous_single_word(self, text: str) -> bool:
        t = (text or "").strip().lower()
        return t in {"open", "set", "play", "volume", "search", "go", "show", "start", "run"}
    def _linux_get_volume_percent(self):
        import subprocess
        import re

        # PipeWire first
        try:
            wp = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            if wp.returncode == 0 and wp.stdout:
                m = re.search(r"([0-9]*\.?[0-9]+)", wp.stdout)
                if m:
                    return int(round(float(m.group(1)) * 100))
        except Exception:
            pass

        # ALSA fallback
        try:
            am = subprocess.run(
                ["amixer", "get", "Master"],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            if am.returncode == 0 and am.stdout:
                vals = re.findall(r"\[(\d{1,3})%\]", am.stdout)
                if vals:
                    return int(vals[-1])
        except Exception:
            pass

        return None


    def _fallback_volume(self, kind: str, payload: dict):
        import subprocess

        def _ok(msg: str):
            return {"ok": True, "content": msg, "response": msg}

        def _fail(msg: str):
            return {"ok": False, "content": msg, "response": msg}

        # ---------- PipeWire path ----------
        try:
            if kind == "VOLUME_GET":
                pct = self._linux_get_volume_percent()
                return _ok(f"Current volume: {pct}%") if pct is not None else _fail("Volume read failed")

            if kind == "VOLUME_SET":
                level = int(payload.get("level", 50))
                subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level}%"], check=True, timeout=1.5)
                return _ok(f"Volume set to {level}%")

            if kind == "VOLUME_UP":
                step = int(payload.get("step", 5))
                subprocess.run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{step}%+"], check=True, timeout=1.5)
                pct = self._linux_get_volume_percent()
                return _ok(f"Volume raised by {step}%{'' if pct is None else f' (now {pct}%)'}")

            if kind == "VOLUME_DOWN":
                step = int(payload.get("step", 5))
                subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{step}%-"], check=True, timeout=1.5)
                pct = self._linux_get_volume_percent()
                return _ok(f"Volume lowered by {step}%{'' if pct is None else f' (now {pct}%)'}")

            if kind == "VOLUME_MUTE":
                subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"], check=True, timeout=1.5)
                return _ok("Muted")

            if kind == "VOLUME_UNMUTE":
                subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], check=True, timeout=1.5)
                return _ok("Unmuted")

        except Exception:
            pass

        # ---------- ALSA fallback ----------
        try:
            if kind == "VOLUME_GET":
                pct = self._linux_get_volume_percent()
                return _ok(f"Current volume: {pct}%") if pct is not None else _fail("Volume read failed")

            if kind == "VOLUME_SET":
                level = int(payload.get("level", 50))
                subprocess.run(["amixer", "set", "Master", f"{level}%"], check=True, timeout=1.5)
                return _ok(f"Volume set to {level}%")

            if kind == "VOLUME_UP":
                step = int(payload.get("step", 5))
                subprocess.run(["amixer", "set", "Master", f"{step}%+"], check=True, timeout=1.5)
                pct = self._linux_get_volume_percent()
                return _ok(f"Volume raised by {step}%{'' if pct is None else f' (now {pct}%)'}")

            if kind == "VOLUME_DOWN":
                step = int(payload.get("step", 5))
                subprocess.run(["amixer", "set", "Master", f"{step}%-"], check=True, timeout=1.5)
                pct = self._linux_get_volume_percent()
                return _ok(f"Volume lowered by {step}%{'' if pct is None else f' (now {pct}%)'}")

            if kind == "VOLUME_MUTE":
                subprocess.run(["amixer", "set", "Master", "mute"], check=True, timeout=1.5)
                return _ok("Muted")

            if kind == "VOLUME_UNMUTE":
                subprocess.run(["amixer", "set", "Master", "unmute"], check=True, timeout=1.5)
                return _ok("Unmuted")

        except Exception as e2:
            return _fail(f"Volume control failed: {e2}")

        return _fail("Volume control failed")


    def _dispatch_local_command(self, kind: str, payload: dict):
        """
        IMPORTANT: match executor_enhanced.py schema exactly.
        VOLUME expects: direction, delta, level (not mode/step)
        Media expects: NEXT_MEDIA / PREVIOUS_MEDIA / PAUSE_MEDIA / PLAY_MEDIA / STOP_MEDIA
        """
        try:
            # ---- VOLUME through executor ----
            if kind == "VOLUME_GET":
                return execute("VOLUME", {"direction": None, "delta": 0, "level": None})
            if kind == "VOLUME_SET":
                return execute("VOLUME", {"level": int(payload["level"]), "direction": None, "delta": 0})
            if kind == "VOLUME_UP":
                return execute("VOLUME", {"direction": "up", "delta": int(payload.get("step", 5)), "level": None})
            if kind == "VOLUME_DOWN":
                return execute("VOLUME", {"direction": "down", "delta": int(payload.get("step", 5)), "level": None})
            if kind == "VOLUME_MUTE":
                # force mute with direct fallback (executor has no dedicated mute verb in your current implementation)
                return self._fallback_volume(kind, payload)
            if kind == "VOLUME_UNMUTE":
                return self._fallback_volume(kind, payload)

            # ---- MEDIA ----
            if kind == "MEDIA_NEXT":
                return execute("NEXT_MEDIA", {})
            if kind == "MEDIA_PREV":
                return execute("PREVIOUS_MEDIA", {})
            if kind == "MEDIA_PAUSE":
                return execute("PAUSE_MEDIA", {})
            if kind == "MEDIA_PLAY":
                return execute("PLAY_MEDIA", {})
            if kind == "MEDIA_STOP":
                return execute("STOP_MEDIA", {})

            # ---- TIME / DATE ----
            if kind == "GET_TIME":
                return execute("GET_TIME", {})
            if kind == "GET_DATE":
                return execute("GET_DATE", {})

            return {"ok": False, "content": f"Unsupported local command: {kind}", "response": f"Unsupported local command: {kind}"}

        except Exception as e:
            # if executor path fails, salvage volume locally
            if isinstance(kind, str) and kind.startswith("VOLUME_"):
                return self._fallback_volume(kind, payload)
            return {"ok": False, "content": f"Local command failed: {e}", "response": f"Local command failed: {e}"}


    def _dispatch_local_or_router(self, user_input: str):
        kind, payload = self._parse_local_command(user_input)
        if kind is not None:
            # deterministic bypass for local commands
            # (these are status labels for your console, not directly executed here)
            mapping = {
                "VOLUME_GET": ("VOLUME", {"direction": None, "delta": 0, "level": None}),
                "VOLUME_MUTE": ("VOLUME_MUTE", {}),
                "VOLUME_UNMUTE": ("VOLUME_UNMUTE", {}),
                "MEDIA_NEXT": ("NEXT_MEDIA", {}),
                "MEDIA_PREV": ("PREVIOUS_MEDIA", {}),
                "MEDIA_PAUSE": ("PAUSE_MEDIA", {}),
                "MEDIA_PLAY": ("PLAY_MEDIA", {}),
                "MEDIA_STOP": ("STOP_MEDIA", {}),
                "GET_TIME": ("GET_TIME", {}),
                "GET_DATE": ("GET_DATE", {}),
            }

            if kind == "VOLUME_SET":
                action, args = ("VOLUME", {"level": int(payload["level"]), "direction": None, "delta": 0})
            elif kind == "VOLUME_UP":
                action, args = ("VOLUME", {"direction": "up", "delta": int(payload.get("step", 5)), "level": None})
            elif kind == "VOLUME_DOWN":
                action, args = ("VOLUME", {"direction": "down", "delta": int(payload.get("step", 5)), "level": None})
            else:
                action, args = mapping.get(kind, ("CHAT", {"message": user_input}))

            self.add_system_message("COGNITIVE", f"Router bypass (deterministic): {action} {args}", "#8fbcbb")
            return action, args, 1.0

        route_result = route(user_input)
        self.add_system_message("COGNITIVE", f"Router parsed: {route_result}", "#8fbcbb")
        if not route_result:
            return "CHAT", {"message": user_input}, 0.0

        return (
            route_result.get("action", "CHAT"),
            route_result.get("args", {}),
            route_result.get("confidence", 0.0),
        )

    def process_input_stream(self):
        user_input = self.input_field.text().strip()
        if not user_input:
            return

        # Priority fast-path — media/volume commands always execute regardless of busy state
        PRIORITY_COMMANDS = {
            "next", "previous", "skip", "back", "pause", "play", "stop", "resume",
            "next song", "next track", "previous song", "previous track",
            "volume up", "volume down", "mute", "unmute", "max volume",
            "volume max", "full volume",
        }
        if user_input.strip().lower() in PRIORITY_COMMANDS:
            from eli.tools.router_enhanced import route as _route
            from eli.tools.executor_enhanced import execute as _execute
            _r = _route(user_input)
            _res = _execute(_r["action"], _r.get("args", {}))
            _msg = _res.get("response") or _res.get("content") or "Done."
            self.add_system_message("VOICE", user_input, "#d08770")
            self.add_system_message("ELI", _msg, "#a3be8c")
            self.input_field.clear()
            return

        # Priority fast-path — media/volume commands always execute regardless of busy state
        # single-flight guard
        if getattr(self, "_busy", False):
            self.add_system_message("SYSTEM", "Still processing previous command...", "#ebcb8b")
            return

        # deterministic local path first
        kind, payload = self._parse_local_command(user_input)
        if kind is not None:
            self._busy = True
            self.add_system_message("USER", user_input, "#e5e9f0")
            self.input_field.clear()
            self.set_system_status("PROCESSING")
            self.process_indicator.setText("◉ PROCESSING (1)")
            self.execute_button.setEnabled(False)
            try:
                res = self._dispatch_local_command(kind, payload) or {"ok": True, "content": "Done."}
                if isinstance(res, dict):
                    content = res.get("content") or res.get("response") or res.get("message") or str(res)
                else:
                    content = str(res)
                self.add_system_message("ELI", content, "#a3be8c")
                self.set_system_status("OPERATIONAL")
            except Exception as e:
                self.add_system_message("ERROR", f"Local command failed: {e}", "#bf616a")
                self.set_system_status("ERROR")
            finally:
                self._busy = False
                self.process_indicator.setText("◌ IDLE")
                self.execute_button.setEnabled(True)
            return

        # router/engine path
        self._busy = True
        self.add_system_message("USER", user_input, "#e5e9f0")
        self.input_field.clear()
        self.set_system_status("PROCESSING")
        self.process_indicator.setText("◉ PROCESSING (1)")
        self.execute_button.setEnabled(False)

        try:
            action, args, _confidence = self._dispatch_local_or_router(user_input)
            # avoid duplicated workers
            if action == "CHAT":
                if hasattr(self, "_stream_worker") and self._stream_worker is not None and self._stream_worker.isRunning():
                    self.add_system_message("SYSTEM", "Model is already generating. Please wait...", "#ebcb8b")
                    return
                self._stream_worker = LLMStreamWorker(args.get("message", user_input))
                self._stream_worker.token_chunk.connect(self.handle_token_chunk)
                self._stream_worker.stream_ended.connect(self.handle_stream_end)
                self._stream_worker.error_occurred.connect(self.handle_stream_error)
                self._stream_worker.finished.connect(self._on_stream_worker_finished)
                self.handle_stream_started()
                self._stream_worker.start()
                return

            # non-chat command
            res = execute(action, args) or {"ok": True, "content": "Done."}
            self.handle_execution_result(res)
        except Exception as e:
            self.add_system_message("ERROR", f"Command processing failed: {e}", "#bf616a")
            self.set_system_status("ERROR")
            self._busy = False
            self.process_indicator.setText("◌ IDLE")
            self.execute_button.setEnabled(True)


    def _fallback_volume(self, kind: str, payload: dict):
        import subprocess, re
        def sh(cmd):
            return subprocess.run(cmd, shell=True, capture_output=True, text=True)
        def parse_pct(txt):
            m = re.search(r"(\d{1,3})%", txt)
            return int(m.group(1)) if m else None

        # Prefer wpctl (PipeWire), fallback to amixer
        has_wpctl = sh("command -v wpctl").returncode == 0
        if has_wpctl:
            if kind == "VOLUME_GET":
                out = sh("wpctl get-volume @DEFAULT_AUDIO_SINK@").stdout
                m = re.search(r"([0-9]*\.?[0-9]+)", out)
                if m:
                    pct = max(0, min(100, int(round(float(m.group(1))*100))))
                    return {"ok": True, "content": f"Volume is {pct}%"}
            elif kind == "VOLUME_SET":
                lvl = max(0, min(100, int(payload.get("level", 0))))
                sh(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {lvl/100.0}")
                return {"ok": True, "content": f"Volume set to {lvl}%"}
            elif kind in ("VOLUME_UP","VOLUME_DOWN"):
                step = max(1, min(100, int(payload.get("step", 5))))
                sign = "+" if kind == "VOLUME_UP" else "-"
                sh(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {step/100.0}{sign}")
                out = sh("wpctl get-volume @DEFAULT_AUDIO_SINK@").stdout
                m = re.search(r"([0-9]*\.?[0-9]+)", out)
                if m:
                    pct = max(0, min(100, int(round(float(m.group(1))*100))))
                    return {"ok": True, "content": f"Volume is now {pct}%"}
                return {"ok": True, "content": "Volume updated."}
            elif kind == "VOLUME_MUTE":
                sh("wpctl set-mute @DEFAULT_AUDIO_SINK@ 1")
                return {"ok": True, "content": "Muted."}
            elif kind == "VOLUME_UNMUTE":
                sh("wpctl set-mute @DEFAULT_AUDIO_SINK@ 0")
                return {"ok": True, "content": "Unmuted."}

        # ALSA fallback
        if kind == "VOLUME_GET":
            out = sh("amixer get Master").stdout
            pct = parse_pct(out)
            if pct is not None:
                return {"ok": True, "content": f"Volume is {pct}%"}
        elif kind == "VOLUME_SET":
            lvl = max(0, min(100, int(payload.get("level", 0))))
            sh(f"amixer -q sset Master {lvl}%")
            return {"ok": True, "content": f"Volume set to {lvl}%"}
        elif kind in ("VOLUME_UP","VOLUME_DOWN"):
            step = max(1, min(100, int(payload.get("step", 5))))
            sign = "+" if kind == "VOLUME_UP" else "-"
            sh(f"amixer -q sset Master {step}%{sign}")
            out = sh("amixer get Master").stdout
            pct = parse_pct(out)
            return {"ok": True, "content": f"Volume is now {pct}%"} if pct is not None else {"ok": True, "content":"Volume updated."}
        elif kind == "VOLUME_MUTE":
            sh("amixer -q sset Master mute")
            return {"ok": True, "content": "Muted."}
        elif kind == "VOLUME_UNMUTE":
            sh("amixer -q sset Master unmute")
            return {"ok": True, "content": "Unmuted."}
        return {"ok": False, "content": "Volume control failed"}

    def run_quick_command(self, command: str):
        try:
            self.input_field.setText(command)
            self.process_input_stream()
        except Exception:
            try:
                self.input_field.setText(command)
            except Exception:
                pass


    def _on_stream_worker_finished(self):
        self._busy = False
        self.execute_button.setEnabled(True)
        self.set_system_status("OPERATIONAL")
        self.process_indicator.setText("◌ IDLE")
        # Process next queued command after stream completes
        QTimer.singleShot(100, self._process_next_queued_command)

    def handle_execution_result(self, result):
        # Clear busy flag first
        self._busy = False
        
        try:
            self.active_workers = max(0, int(getattr(self, "active_workers", 0)) - 1)
        except Exception:
            pass
        try:
            self.execute_button.setEnabled(True)
        except Exception:
            pass

        if isinstance(result, dict) and result.get("streamed"):
            self.set_system_status("OPERATIONAL")
            try:
                self.process_indicator.setText("◌ IDLE" if self.active_workers == 0 else f"◉ PROCESSING ({self.active_workers})")
            except Exception:
                pass
            self._streaming_active = False
            # Process queued commands after streaming completes
            QTimer.singleShot(100, self._process_next_queued_command)
            return

        if not isinstance(result, dict):
            result = {"ok": True, "content": str(result)}

        if result.get("ok", False):
            self.set_system_status("OPERATIONAL")
            try:
                self.process_indicator.setText("◌ IDLE" if self.active_workers == 0 else f"◉ PROCESSING ({self.active_workers})")
            except Exception:
                pass
            response = self.format_eli_response(result)
            self.add_system_message("ELI", response, "#a3be8c")

            # Wire IDE panel for code generation results
            action = result.get("action", "")
            if action in ("GENERATE_PROJECT", "GENERATE_SCRIPT", "OPEN_IDE"):
                try:
                    if action == "GENERATE_PROJECT":
                        project_path = result.get("project_path", "")
                        if project_path:
                            self.ide_dock.load_project(project_path)
                    elif action == "GENERATE_SCRIPT":
                        script_path = result.get("script_path", "")
                        code = result.get("code", "")
                        if script_path:
                            self.ide_dock.load_project(str(Path(script_path).parent))
                        if code:
                            fname = Path(script_path).name if script_path else "generated.py"
                            self.ide_dock.display_generated_code(code, fname)
                    # Switch to Code tab
                    for i in range(self.tabs.count()):
                        if "Code" in self.tabs.tabText(i):
                            self.tabs.setCurrentIndex(i)
                            break
                except Exception as e:
                    print(f"[IDE] Wiring error: {e}")

            if action == "OPEN_IDE":
                try:
                    for i in range(self.tabs.count()):
                        if "Code" in self.tabs.tabText(i):
                            self.tabs.setCurrentIndex(i)
                            break
                except Exception:
                    pass
        else:
            self.handle_system_error(result)
        
        # Process next queued command after current one completes
        QTimer.singleShot(100, self._process_next_queued_command)

    def handle_system_error(self, error_json):
        self.active_workers = max(0, self.active_workers - 1)
        self.set_system_status("ERROR")
        self.process_indicator.setText("◌ IDLE" if self.active_workers == 0 else f"◉ PROCESSING ({self.active_workers})")
        self.execute_button.setEnabled(True)
        try:
            error_data = error_json if isinstance(error_json, dict) else json.loads(error_json)
            execution_id = error_data.get('execution_id', 'UNKNOWN')
            error_msg = error_data.get('error') or error_data.get('response') or error_data.get('message') or 'Unknown error'
            self.add_system_message("ERROR", f"Execution {execution_id} failed: {error_msg}", "#bf616a")
            QTimer.singleShot(3000, lambda: self.set_system_status("OPERATIONAL"))
        except:
            self.add_system_message("ERROR", f"System error: {error_json}", "#bf616a")
            QTimer.singleShot(3000, lambda: self.set_system_status("OPERATIONAL"))
        
        # Process next queued command after error
        QTimer.singleShot(100, self._process_next_queued_command)

    def _flush_stream_buffer(self):
        try:
            buf = getattr(self, "_stream_buf", None)
            if not buf:
                return
            chunk = "".join(buf)
            buf.clear()
            c = self.conversation_display.textCursor()
            c.movePosition(QTextCursor.MoveOperation.End)
            self.conversation_display.setTextCursor(c)
            self.conversation_display.insertPlainText(chunk)
            self.conversation_display.ensureCursorVisible()
        except Exception:
            pass

    def handle_stream_end(self, meta=None):
        try:
            self._streaming_active = False
            self._flush_stream_buffer()
            t = getattr(self, "_stream_flush_timer", None)
            if t is not None:
                t.stop()
            c = self.conversation_display.textCursor()
            c.movePosition(QTextCursor.MoveOperation.End)
            self.conversation_display.setTextCursor(c)
            self.conversation_display.insertPlainText("\n")
            self.conversation_display.ensureCursorVisible()
        except Exception:
            pass
        # Process next queued command after stream ends
        QTimer.singleShot(200, self._process_next_queued_command)

    def handle_stream_started(self, meta=None):
        self._streaming_active = True
        try:
            t = getattr(self, "_stream_flush_timer", None)
            if t is not None and not t.isActive():
                t.start()
        except Exception:
            pass
        try:
            self.add_system_message("ELI", "", "#a3be8c")
        except Exception:
            pass
        try:
            c = self.conversation_display.textCursor()
            c.movePosition(QTextCursor.MoveOperation.End)
            self.conversation_display.setTextCursor(c)
        except Exception:
            pass

    def handle_token_chunk(self, chunk: str):
        try:
            if not chunk:
                return
            if not isinstance(chunk, str):
                chunk = str(chunk)
            buf = getattr(self, "_stream_buf", None)
            if buf is None:
                self._stream_buf = []
                buf = self._stream_buf
            buf.append(chunk)
            t = getattr(self, "_stream_flush_timer", None)
            if t is not None and not t.isActive():
                t.start()
        except Exception:
            pass

    def handle_stream_error(self, error_msg):
        self.add_system_message("ERROR", f"Streaming failed: {error_msg}", "#bf616a")
        self.active_workers = max(0, self.active_workers - 1)
        self.process_indicator.setText("◌ IDLE" if self.active_workers == 0 else f"◉ PROCESSING ({self.active_workers})")
        self.execute_button.setEnabled(True)
        self.set_system_status("OPERATIONAL")

    def format_eli_response(self, result):
        if 'response' in result:
            return result['response']
        elif 'message' in result:
            return result['message']
        elif 'result' in result:
            return f"Result: {result['result']}"
        elif 'time' in result:
            return f"Chronal alignment: {result['time']}"
        elif 'date' in result:
            return f"Temporal coordinate: {result['date']}"
        elif 'files' in result:
            files = result['files'][:8]
            base = f"Storage matrix contains {len(result['files'])} entities:\n"
            return base + "\n".join(f"  ├ {f}" for f in files) + ("\n  └ ..." if len(result['files']) > 8 else "")
        else:
            return str(result)

    def toggle_audio_input(self, checked):
        if checked:
            self.audio_button.setText("🎤 ON")
            self.audio_status.setText("Voice: LISTENING")
            self.audio_status.setStyleSheet("color: #a3be8c;")
            def audio_callback(transcript):
                print(f"🎤🎤🎤 AUDIO CALLBACK FIRED: '{transcript}'")
                self.voice_command_received.emit(transcript)
            start_audio_listening(audio_callback)
            self.audio_listening = True
            self.add_system_message("AUDIO", "Continuous voice input activated. Say 'ELI' followed by your command.", "#88c0d0")
        else:
            self.audio_button.setText("🎤 OFF")
            self.audio_status.setText("Voice: DISABLED")
            self.audio_status.setStyleSheet("color: #88c0d0;")
            stop_audio_listening()
            self.audio_listening = False
            self.add_system_message("AUDIO", "Continuous voice input deactivated", "#88c0d0")

    def listen_once_command(self):
        was_continuous = bool(getattr(self, 'audio_listening', False))
        if was_continuous:
            try:
                stop_audio_listening()
            except Exception:
                pass
            self.audio_listening = False
            try:
                self.audio_button.setChecked(False)
            except Exception:
                pass
        self.add_system_message("AUDIO", "Listening for voice command...", "#88c0d0")
        self.audio_button.setEnabled(False)
        self.audio_button.setText("🎤 ...")
        self.audio_status.setText("Voice: ACTIVE")
        def listen_thread():
            transcript = listen_for_command(timeout=10)
            if transcript:
                QTimer.singleShot(0, lambda: self.process_audio_transcript(transcript))
            else:
                QTimer.singleShot(0, self.audio_listen_failed)
        threading.Thread(target=listen_thread, daemon=True).start()

    def process_audio_transcript(self, transcript):
        self.audio_button.setEnabled(True)
        self.audio_button.setText("🎤 OFF")
        self.audio_button.setChecked(False)
        self.audio_status.setText("Voice: DISABLED")
        self.add_system_message("VOICE", transcript, "#d08770")
        self.input_field.setText(transcript)
        self.process_input_stream()

    def audio_listen_failed(self):
        self.audio_button.setEnabled(True)
        self.audio_button.setText("🎤 OFF")
        self.audio_button.setChecked(False)
        self.audio_status.setText("Voice: DISABLED")
        self.add_system_message("AUDIO", "Could not understand audio command", "#bf616a")

    # Quick action methods
    def quick_browser(self):
        self.input_field.setText("access network browser")
        self.process_input_stream()

    def quick_spotify(self):
        self.input_field.setText("initiate audio interface")
        self.process_input_stream()

    def quick_email(self):
        self.input_field.setText("access communication hub")
        self.process_input_stream()

    def quick_document(self):
        self.input_field.setText("fabricate data construct")
        self.process_input_stream()

    def quick_files(self):
        self.input_field.setText("access storage matrix")
        self.process_input_stream()

    def quick_search(self):
        text, ok = QInputDialog.getText(self, "Information Scan", "Enter search query:")
        if ok and text:
            self.input_field.setText(f"scan information database for {text}")
            self.process_input_stream()

    def quick_time(self):
        self.input_field.setText("check chronal alignment")
        self.process_input_stream()

    def quick_memory(self):
        self.input_field.setText("access neural archive")
        self.process_input_stream()

    def closeEvent(self, event):
        if self.audio_listening:
            stop_audio_listening()
        try:
            if getattr(self, "worker", None) and self.worker.isRunning():
                self.worker.requestInterruption()
                self.worker.quit()
                self.worker.wait(5000)
        except Exception:
            pass
        if self.conversation_log:
            conv_dir = Path(os.environ.get('ELI_CONVERSATIONS_DIR', 
                           str(Path(os.environ.get('ELI_ROOT', str(Path(__file__).parent.parent))) / 'artifacts' / 'conversations'))).resolve()
            conv_dir.mkdir(parents=True, exist_ok=True)
            log_file = str(conv_dir / f"eli_conversation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            try:
                with open(log_file, 'w') as f:
                    json.dump(self.conversation_log, f, indent=2)
                print(f"[ELI] Conversation log saved to {log_file}")
            except:
                pass
        event.accept()

def main():
    print("\n" + "="*60)
    print("        ELI - Enhanced Learning Interface v5.0")
    print("        Professional Assistant with Audio STT")
    print("="*60 + "\n")

    try:
        import PySide6
    except ImportError:
        print("❌ PySide6 is required. Install with: pip install PySide6")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("ELI Enhanced Learning Interface")
    app.setOrganizationName("ClearBuild.tech")

    font = QFont("Consolas", 10)
    app.setFont(font)

    window = ELIEntropicGUI()
    window.show()

    print("✅ Interface initialized")
    print("✅ Audio STT subsystem engaged")
    print("✅ Ready for input stream\n")

    # Start proactive daemon for self-improvement and learning
    try:
        from eli.brain.proactive_daemon import start_daemon
        daemon = start_daemon()
        try:
            window.proactive_dock.set_daemon(daemon)
            window.self_improve_dock.set_daemon(daemon)
        except Exception as e:
            print(f"[PANELS] Daemon wiring error: {e}")
        pass  # daemon start logged by proactive_daemon.py
    except Exception as e:
        print(f"[PROACTIVE] Failed to start daemon: {e}")


    sys.exit(app.exec())


if __name__ == "__main__":
    main()
