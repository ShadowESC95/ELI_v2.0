"""One-click GUI installer — backend terminal work with OS-style progress and ELI wit."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from eli.gui.qt_compat import (
    Qt,
    QTimer,
    QThread,
    pyqtSignal,
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from eli.setup.install_backend import (
    InstallProgress,
    install_script_path,
    parse_install_line,
    python3_available,
    run_install_streaming,
)
from eli.setup.install_messages import messages_for_phase, phase_label
from eli.setup.platform_profile import (
    InstallProfile,
    detect_install_profile,
    get_platform_info,
)
from eli.setup.status import (
    has_chat_model,
    has_venv,
    project_root,
    stage_checks,
    venv_python,
)
from eli.setup.wizard import _SetupWorker, _WIZARD_QSS

try:
    from PySide6.QtWidgets import QGraphicsOpacityEffect
except Exception:
    try:
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
    except Exception:
        QGraphicsOpacityEffect = None  # type: ignore


class _FadeMessageLabel(QLabel):
    """Rolling installer copy with opacity cross-fade."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setMinimumHeight(72)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "color:#d8dee9;font-size:15px;font-weight:500;line-height:1.45;padding:12px 8px;"
        )
        self._pool: List[str] = []
        self._idx = 0
        self._opacity = 1.0
        self._effect = None
        if QGraphicsOpacityEffect is not None:
            self._effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(self._effect)
        self._timer = QTimer(self)
        self._timer.setInterval(4500)
        self._timer.timeout.connect(self._rotate)
        self._fade = QTimer(self)
        self._fade.setInterval(40)
        self._fade_step = -0.08
        self._fade.timeout.connect(self._tick_fade)

    def set_phase(self, phase: str) -> None:
        self._pool = messages_for_phase(phase)
        self._idx = 0
        self._show_current()

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._fade.stop()
        if self._effect:
            self._effect.setOpacity(1.0)

    def _show_current(self) -> None:
        if not self._pool:
            return
        self.setText(f"“{self._pool[self._idx % len(self._pool)]}”")
        if self._effect:
            self._effect.setOpacity(1.0)

    def _rotate(self) -> None:
        if len(self._pool) <= 1:
            return
        self._fade_step = -0.10
        self._fade.start()

    def _tick_fade(self) -> None:
        if self._effect is None:
            self._idx += 1
            self._show_current()
            self._fade.stop()
            return
        self._opacity += self._fade_step
        self._effect.setOpacity(max(0.0, min(1.0, self._opacity)))
        if self._opacity <= 0.0:
            self._idx += 1
            self._show_current()
            self._fade_step = 0.10
            self._opacity = 0.0
        elif self._opacity >= 1.0:
            self._fade.stop()
            self._opacity = 1.0
            self._effect.setOpacity(1.0)


class _InstallShellWorker(QThread):
    line = pyqtSignal(str)
    progress = pyqtSignal(object)
    finished_install = pyqtSignal(int, str)

    def run(self) -> None:
        root = project_root()
        try:
            code, log_path = run_install_streaming(
                root=root,
                on_line=lambda ln: self.line.emit(ln),
                on_progress=lambda p: self.progress.emit(p),
            )
            self.finished_install.emit(code, log_path)
        except Exception as exc:
            self.line.emit(f"[ERROR] {exc}")
            self.finished_install.emit(1, str(exc))


class UnifiedInstallWizard(QDialog):
    """Full one-click installer: install.sh backend + asset stages + launch."""

    def __init__(self, parent=None, *, launch_after: bool = True):
        super().__init__(parent)
        self._launch_after = launch_after
        self._root = project_root()
        self._platform = get_platform_info()
        self._headless_only = self._platform.profile == InstallProfile.ANDROID_HEADLESS
        self._started = time.monotonic()
        self._step_labels: Dict[str, QLabel] = {}
        self._install_worker: Optional[_InstallShellWorker] = None
        self._setup_worker: Optional[_SetupWorker] = None
        self._phase = "welcome"
        self._post_base = 85
        self._post_total = 1
        self._post_done = 0

        self.setWindowTitle("ELI Setup")
        self.setMinimumSize(720, 520)
        self.setStyleSheet(_WIZARD_QSS + """
            QLabel#subtitle { color: #aab3c5; font-size: 12px; }
            QLabel#statusBar { color: #81a1c1; font-size: 11px; }
            QLabel#timeLabel { color: #6f8098; font-size: 11px; }
            QFrame#divider { background: #2a2e38; max-height: 1px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(10)

        title = QLabel("ELI v2.0 — Setup")
        title.setObjectName("title")
        layout.addWidget(title)

        if self._headless_only:
            sub_text = (
                "Android / Termux — headless runtime only. No desktop GUI, no CUDA, "
                "no global screen control. CPU inference with a small model."
            )
        elif self._platform.profile == InstallProfile.WINDOWS_WOA:
            sub_text = (
                "Windows on ARM (Snapdragon) — unified installer. Adreno GPU uses "
                "shared memory; Vulkan offload is experimental on WoA."
            )
        else:
            sub_text = (
                "One-click install for every platform. Backend work runs here — "
                "no terminal juggling, no silent failures."
            )
        sub = QLabel(sub_text)
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        self._fade_msg = _FadeMessageLabel()
        layout.addWidget(self._fade_msg)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("%p% — %v / 100")
        layout.addWidget(self._progress)

        row = QHBoxLayout()
        self._status = QLabel("Preparing…")
        self._status.setObjectName("statusBar")
        self._status.setWordWrap(True)
        row.addWidget(self._status, stretch=1)
        self._elapsed = QLabel("Elapsed: 0:00")
        self._elapsed.setObjectName("timeLabel")
        row.addWidget(self._elapsed)
        layout.addLayout(row)

        div = QFrame()
        div.setObjectName("divider")
        div.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(div)

        for sid, label, done in stage_checks():
            row_lbl = QLabel(f"{'✓' if done else '○'}  {label}")
            row_lbl.setObjectName("stageDone" if done else "stageTodo")
            self._step_labels[sid] = row_lbl
            layout.addWidget(row_lbl)

        self._log = QLabel("")
        self._log.setWordWrap(True)
        self._log.setStyleSheet("color:#5c6a7a;font-size:10px;")
        layout.addWidget(self._log)

        btn_row = QHBoxLayout()
        self._launch_btn = QPushButton(
            "Run headless CLI" if self._headless_only else "Launch ELI"
        )
        self._launch_btn.setObjectName("primary")
        self._launch_btn.setEnabled(False)
        self._retry_btn = QPushButton("Retry install")
        self._retry_btn.setVisible(False)
        self._close_btn = QPushButton("Close")
        btn_row.addWidget(self._launch_btn)
        btn_row.addWidget(self._retry_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

        self._launch_btn.clicked.connect(self._launch_eli)
        self._retry_btn.clicked.connect(self._start_full_install)
        self._close_btn.clicked.connect(self.reject)

        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick_clock)

    def _tick_clock(self) -> None:
        secs = int(time.monotonic() - self._started)
        self._elapsed.setText(f"Elapsed: {secs // 60}:{secs % 60:02d}")

    def _refresh_steps(self) -> None:
        for sid, label, done in stage_checks():
            lbl = self._step_labels.get(sid)
            if lbl:
                lbl.setText(f"{'✓' if done else '○'}  {label}")
                lbl.setObjectName("stageDone" if done else "stageTodo")
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)
        self._launch_btn.setEnabled(has_venv() and has_chat_model())

    def _set_phase(self, phase: str, pct: int, message: str = "") -> None:
        self._phase = phase
        self._progress.setValue(max(0, min(100, int(pct))))
        label = phase_label(phase)
        detail = message.strip() if message else label
        self._status.setText(f"{label}: {detail}")
        self._fade_msg.set_phase(phase)

    def run_auto(self) -> None:
        ok, ver = python3_available()
        if not ok:
            QMessageBox.critical(
                self,
                "Python required",
                f"Python 3.10+ is required before ELI can install.\n\nDetected: {ver or 'none'}",
            )
            self.reject()
            return
        try:
            install_script_path(self._root)
        except FileNotFoundError as exc:
            QMessageBox.critical(self, "Installer missing", str(exc))
            self.reject()
            return

        self._started = time.monotonic()
        self._clock.start()
        self._fade_msg.set_phase("welcome")
        self._fade_msg.start()
        self._set_phase("welcome", 2, f"Python {ver} OK")

        if has_venv():
            self._set_phase("core_install", 40, "Environment present — checking remaining stages")
            self._run_post_install_stages()
        else:
            self._start_full_install()

    def _start_full_install(self) -> None:
        self._retry_btn.setVisible(False)
        self._launch_btn.setEnabled(False)
        self._set_phase("core_install", 5, "Starting core installation…")
        self._install_worker = _InstallShellWorker()
        self._install_worker.line.connect(self._on_install_line)
        self._install_worker.progress.connect(self._on_install_progress)
        self._install_worker.finished_install.connect(self._on_install_finished)
        self._install_worker.start()

    def _on_install_line(self, line: str) -> None:
        clean = line.strip()
        if len(clean) > 120:
            clean = clean[:117] + "…"
        self._log.setText(clean)

    def _on_install_progress(self, prog: InstallProgress) -> None:
        pct = prog.percent if prog.percent > 0 else self._progress.value()
        if prog.phase:
            self._set_phase(prog.phase, pct, prog.message or phase_label(prog.phase))
        elif prog.message:
            self._status.setText(prog.message)

    def _on_install_finished(self, code: int, log_path: str) -> None:
        self._refresh_steps()
        if code != 0:
            self._fade_msg.stop()
            self._retry_btn.setVisible(True)
            self._status.setText(f"Install failed (exit {code}). Log: {log_path}")
            QMessageBox.critical(
                self,
                "Install failed",
                f"Core installation did not complete.\n\nLog saved to:\n{log_path}\n\n"
                "Fix the reported error and click Retry install.",
            )
            return
        if not has_venv():
            self._fade_msg.stop()
            self._retry_btn.setVisible(True)
            QMessageBox.critical(
                self,
                "Environment missing",
                "Install reported success but .venv is missing.\n\n"
                f"See log: {log_path}",
            )
            return
        self._set_phase("assets_setup", 82, "Core install complete — finishing assets")
        self._run_post_install_stages()

    def _pending_post_stages(self) -> List[str]:
        order = ["database", "embedder", "voice", "chat_model", "desktop"]
        pending: List[str] = []
        if has_venv():
            pending.append("database")
        from eli.setup.status import has_embedder, has_voice_assets, has_desktop_launcher
        if not has_embedder():
            pending.append("embedder")
        if not has_voice_assets() and not self._headless_only:
            pending.append("voice")
        if not has_chat_model():
            pending.append("chat_model")
        if not has_desktop_launcher() and not self._headless_only:
            pending.append("desktop")
        return [s for s in order if s in pending]

    def _run_post_install_stages(self) -> None:
        stages = self._pending_post_stages()
        if not stages:
            self._on_all_finished(True, "Everything already set up.")
            return
        base_pct = 85
        self._setup_worker = _SetupWorker(stages)
        self._setup_worker.log.connect(
            lambda msg: self._status.setText(msg)
        )
        self._setup_worker.stage_done.connect(self._on_post_stage_done)
        self._setup_worker.finished_all.connect(self._on_all_finished)
        self._post_base = base_pct
        self._post_total = len(stages)
        self._post_done = 0
        self._setup_worker.start()

    def _on_post_stage_done(self, sid: str) -> None:
        self._post_done += 1
        pct = self._post_base + int(14 * self._post_done / max(1, self._post_total))
        self._set_phase(sid, pct, f"Completed: {sid.replace('_', ' ')}")
        self._refresh_steps()

    def _on_all_finished(self, ok: bool, message: str) -> None:
        self._clock.stop()
        self._fade_msg.stop()
        self._refresh_steps()
        if ok:
            self._set_phase("finish", 100, message)
            self._launch_btn.setEnabled(has_venv() and has_chat_model())
            if self._launch_after and has_chat_model():
                self._launch_eli()
        else:
            self._retry_btn.setVisible(True)
            self._status.setText(message)
            QMessageBox.warning(self, "Setup incomplete", message)

    def _launch_eli(self) -> None:
        py = venv_python()
        if not py.exists():
            QMessageBox.warning(self, "Not ready", "Python environment missing.")
            return
        env = os.environ.copy()
        env["ELI_PROJECT_ROOT"] = str(self._root)
        env["PYTHONPATH"] = str(self._root) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        mod = self._platform.launch_command[-1] if self._headless_only else "eli"
        if self._headless_only:
            subprocess.Popen([str(py), "-m", mod], cwd=str(self._root), env=env)
        else:
            subprocess.Popen([str(py), "-m", "eli"], cwd=str(self._root), env=env)
        self.accept()


def _render_terminal_progress(prog: InstallProgress, *, width: int = 40) -> None:
    pct = max(0, min(100, int(prog.percent or 0)))
    filled = int(width * pct / 100)
    bar = "#" * filled + "-" * (width - filled)
    label = phase_label(prog.phase) if prog.phase else "Working"
    detail = (prog.message or label).strip()
    print(f"\r[{bar}] {pct:3d}%  {label}: {detail[:72]:<72}", end="", flush=True)


def run_terminal_headless_installer(*, launch_after: bool = False) -> int:
    """Android / no-display path — same backend as the GUI wizard, terminal UI."""
    info = get_platform_info()
    root = project_root()
    ok, ver = python3_available()
    if not ok:
        print(f"[ERROR] Python 3.10+ required (detected: {ver or 'none'})")
        return 1
    try:
        install_script_path(root)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 1

    print()
    print("=" * 60)
    print(f"  ELI v2.0 — {info.label}")
    print("=" * 60)
    print(f"  {info.gpu_note}")
    print(f"  Python {ver}")
    print()

    last_phase = "welcome"
    pool = messages_for_phase("android" if info.profile == InstallProfile.ANDROID_HEADLESS else "welcome")
    if pool:
        print(f"  “{pool[0]}”")
        print()

    def _on_progress(prog: InstallProgress) -> None:
        nonlocal last_phase
        if prog.phase:
            last_phase = prog.phase
        _render_terminal_progress(prog)

    def _on_line(line: str) -> None:
        if line.startswith("[ERROR]") or line.startswith("[WARN]"):
            print()
            print(line)

    print("Starting install…")
    try:
        code, log_path = run_install_streaming(
            root=root,
            on_line=_on_line,
            on_progress=_on_progress,
        )
    except Exception as exc:
        print()
        print(f"[ERROR] Install subprocess failed: {exc}")
        return 1

    print()
    if code != 0:
        print(f"[ERROR] Install failed (exit {code}). Log: {log_path}")
        return code
    if not has_venv():
        print(f"[ERROR] Install reported success but .venv is missing. Log: {log_path}")
        return 1

    print("[OK] Core install complete.")
    print(f"     Log: {log_path}")
    if launch_after:
        py = venv_python()
        if py.exists():
            print(f"     Launch: {py} -m {info.launch_command[-1]}")
            env = os.environ.copy()
            env["ELI_PROJECT_ROOT"] = str(root)
            env["PYTHONPATH"] = str(root) + (
                os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
            )
            subprocess.Popen([str(py), "-m", info.launch_command[-1]], cwd=str(root), env=env)
    else:
        py = venv_python()
        print(f"     Run headless: {py} -m eli.cli.headless")
    return 0


def run_unified_installer(*, launch_after: bool = False) -> int:
    profile = detect_install_profile()
    if profile == InstallProfile.ANDROID_HEADLESS and not gui_install_available():
        return run_terminal_headless_installer(launch_after=launch_after)

    app = QApplication.instance() or QApplication(sys.argv)
    dlg = UnifiedInstallWizard(launch_after=launch_after)
    dlg.run_auto()
    return dlg.exec()


def ensure_qt_for_installer() -> bool:
    """Ensure PySide6 is importable (bootstrap with system python before venv exists)."""
    try:
        from eli.gui.qt_compat import QApplication  # noqa: F401
        return True
    except Exception:
        pass
    import shutil
    import subprocess as _sp
    py = shutil.which("python3") or shutil.which("python")
    if not py:
        return False
    try:
        _sp.check_call(
            [py, "-m", "pip", "install", "--user", "PySide6>=6.6.0"],
            stdout=_sp.DEVNULL,
            stderr=_sp.DEVNULL,
        )
    except Exception:
        return False
    try:
        from eli.gui.qt_compat import QApplication  # noqa: F401
        return True
    except Exception:
        return False


def gui_install_available() -> bool:
    """True when a graphical session and Qt import are plausible."""
    if detect_install_profile() == InstallProfile.ANDROID_HEADLESS:
        return False
    if sys.platform == "win32":
        return ensure_qt_for_installer()
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return ensure_qt_for_installer()
    return False
