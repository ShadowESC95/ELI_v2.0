"""Grandparent-ready graphical setup wizard — every first-run stage in one place."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Single Qt binding policy lives in eli.gui.qt_compat (PySide6 → PyQt6 → PyQt5 →
# headless stubs). Importing through the shim avoids a broken hard dependency on
# PyQt6 when only PySide6 is installed (the shipped, LGPL-safe binding).
from eli.gui.qt_compat import (
    Qt,
    QThread,
    pyqtSignal,
    QDesktopServices,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from eli.setup.status import (
    has_chat_model,
    has_desktop_launcher,
    has_embedder,
    has_venv,
    has_voice_assets,
    project_root,
    stage_checks,
    venv_python,
)

_WIZARD_QSS = """
QDialog { background: #16181d; }
QWidget { color: #cdd6e4; font-size: 13px; }
QLabel#title { font-size: 20px; font-weight: 700; color: #88c0d0; }
QLabel#stageDone { color: #a3be8c; }
QLabel#stageTodo { color: #ebcb8b; }
QPushButton {
    background: #262a32; color: #e5e9f0; border: 1px solid #363b47;
    border-radius: 8px; padding: 8px 18px; font-weight: 600;
}
QPushButton:hover { background: #2f343d; }
QPushButton#primary { background: #5e81ac; color: #eceff4; border: none; }
QPushButton#primary:hover { background: #6a8fbd; }
QProgressBar {
    background: #21242b; border: 1px solid #333844; border-radius: 7px; height: 14px;
}
QProgressBar::chunk { background: #5e81ac; border-radius: 6px; }
"""


class _SetupWorker(QThread):
    log = pyqtSignal(str)
    stage_done = pyqtSignal(str)
    finished_all = pyqtSignal(bool, str)

    def __init__(self, stages: List[str]):
        super().__init__()
        self._stages = stages
        self._root = project_root()

    def run(self) -> None:
        try:
            for sid in self._stages:
                self.log.emit(f"Running: {sid} …")
                ok = self._run_stage(sid)
                self.stage_done.emit(sid)
                if not ok and sid in ("chat_model", "embedder", "voice"):
                    self.finished_all.emit(False, f"Stage failed: {sid}")
                    return
            self.finished_all.emit(True, "Setup complete.")
        except Exception as exc:
            self.finished_all.emit(False, str(exc))

    def _py(self, *args: str) -> bool:
        py = venv_python()
        if not py.exists():
            return False
        env = os.environ.copy()
        env["ELI_PROJECT_ROOT"] = str(self._root)
        env["PYTHONPATH"] = str(self._root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        proc = subprocess.run([str(py), *args], cwd=str(self._root), env=env)
        return proc.returncode == 0

    def _run_stage(self, sid: str) -> bool:
        if sid == "database":
            return self._py("-m", "eli.core.init_data")
        if sid == "embedder":
            return self._py("-c", "from eli.core.model_download import download_aux; download_aux(required_only=True)")
        if sid == "voice":
            return self._py("-m", "eli.runtime.voice_assets")
        if sid == "chat_model":
            if has_chat_model():
                return True
            if self._restore_github_assets():
                return has_chat_model()
            return self._py("-m", "eli.core.model_download", "--auto")
        if sid == "desktop":
            script = self._root / "scripts" / "install_desktop_apps.sh"
            if not script.exists():
                return False
            proc = subprocess.run(["bash", str(script)], cwd=str(self._root))
            return proc.returncode == 0
        return True

    def _restore_github_assets(self) -> bool:
        script = self._root / "scripts" / "restore_github_asset_files.py"
        if not script.exists():
            return False
        try:
            subprocess.run(["gh", "auth", "status"], capture_output=True, check=True)
        except Exception:
            return False
        repo = os.environ.get("GITHUB_REPOSITORY", "ShadowESC95/ELI_v2.0")
        tag = os.environ.get("ELI_ASSET_RELEASE_TAG", "local-assets-v2.1")
        proc = subprocess.run(
            [str(venv_python()), str(script), "--repo", repo, "--tag", tag],
            cwd=str(self._root),
        )
        return proc.returncode == 0


class GrandparentSetupWizard(QDialog):
    """One-window checklist for every first-run requirement."""

    def __init__(self, parent=None, *, auto_run: bool = True, launch_after: bool = True):
        super().__init__(parent)
        self._launch_after = launch_after
        self.setWindowTitle("ELI Setup")
        self.setMinimumSize(640, 480)
        self.setStyleSheet(_WIZARD_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("ELI v2.0 — First-time setup")
        title.setObjectName("title")
        root.addWidget(title)

        intro = QLabel(
            "This wizard prepares everything ELI needs on your computer — "
            "no terminal knowledge required. Each step is safe to re-run."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#aab3c5;line-height:1.5;")
        root.addWidget(intro)

        self._stage_labels: Dict[str, QLabel] = {}
        for sid, label, done in stage_checks():
            row = QLabel(f"{'✓' if done else '○'}  {label}")
            row.setObjectName("stageDone" if done else "stageTodo")
            self._stage_labels[sid] = row
            root.addWidget(row)

        self._log = QLabel("")
        self._log.setWordWrap(True)
        self._log.setStyleSheet("color:#81a1c1;font-size:11px;")
        root.addWidget(self._log)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("Run setup")
        self._run_btn.setObjectName("primary")
        self._launch_btn = QPushButton("Launch ELI v2.0")
        self._launch_btn.setObjectName("primary")
        self._launch_btn.setEnabled(has_venv() and has_chat_model())
        self._close_btn = QPushButton("Close")
        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._launch_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._close_btn)
        root.addLayout(btn_row)

        self._run_btn.clicked.connect(self._start_setup)
        self._launch_btn.clicked.connect(self._launch_eli)
        self._close_btn.clicked.connect(self.reject)

        self._worker: Optional[_SetupWorker] = None
        if auto_run and not all(ok for _, _, ok in stage_checks()):
            self._start_setup()

    def _refresh_labels(self) -> None:
        for sid, label, done in stage_checks():
            row = self._stage_labels.get(sid)
            if row:
                row.setText(f"{'✓' if done else '○'}  {label}")
                row.setObjectName("stageDone" if done else "stageTodo")
                row.style().unpolish(row)
                row.style().polish(row)
        self._launch_btn.setEnabled(has_venv() and has_chat_model())

    def _pending_stages(self) -> List[str]:
        order = ["database", "embedder", "voice", "chat_model", "desktop"]
        pending: List[str] = []
        if has_venv():
            pending.append("database")
        if not has_embedder():
            pending.append("embedder")
        if not has_voice_assets():
            pending.append("voice")
        if not has_chat_model():
            pending.append("chat_model")
        if not has_desktop_launcher():
            pending.append("desktop")
        return [s for s in order if s in pending]

    def _start_setup(self) -> None:
        if not has_venv():
            QMessageBox.warning(
                self,
                "Install required",
                "The Python environment is not ready yet.\n\n"
                "Please run the ELI Setup desktop icon again, or from this folder run:\n"
                "  bash scripts/eli_setup.sh",
            )
            return
        stages = self._pending_stages()
        if not stages:
            self._log.setText("Everything is already set up.")
            self._refresh_labels()
            return
        self._run_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._worker = _SetupWorker(stages)
        self._worker.log.connect(self._log.setText)
        self._worker.stage_done.connect(lambda _s: self._refresh_labels())
        self._worker.finished_all.connect(self._on_finished)
        self._worker.start()

    def _on_finished(self, ok: bool, message: str) -> None:
        self._progress.setVisible(False)
        self._run_btn.setEnabled(True)
        self._refresh_labels()
        self._log.setText(message)
        if ok:
            self._launch_btn.setEnabled(True)
            if self._launch_after and has_chat_model():
                self._launch_eli()

    def _launch_eli(self) -> None:
        py = venv_python()
        if not py.exists():
            QMessageBox.warning(self, "Not ready", "Python environment missing.")
            return
        root = project_root()
        env = os.environ.copy()
        env["ELI_PROJECT_ROOT"] = str(root)
        env["PYTHONPATH"] = str(root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        subprocess.Popen([str(py), "-m", "eli"], cwd=str(root), env=env)
        self.accept()


def run_wizard(*, auto_run: bool = True, launch_after: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    dlg = GrandparentSetupWizard(auto_run=auto_run, launch_after=launch_after)
    return dlg.exec()
