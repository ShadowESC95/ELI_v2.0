from __future__ import annotations

import os
import signal
import subprocess
from eli.gui.qt_compat import QThread, pyqtSignal
class VoiceWorker(QThread):
    line = pyqtSignal(str)      # raw line from eli-voice stdout
    status = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, *, eli_voice_path: str | None = None, parent=None):
        super().__init__(parent)
        self.eli_voice_path = eli_voice_path or os.path.expanduser("~/bin/eli-voice")
        self._proc: subprocess.Popen[str] | None = None
        self._stop = False

    def stop(self):
        self._stop = True
        p = self._proc
        if not p:
            return
        # polite stop first (matches your Ctrl+C behavior)
        try:
            p.send_signal(signal.SIGINT)
        except Exception:
            pass
        try:
            p.terminate()
        except Exception:
            pass

    def run(self):
        try:
            cmd = [self.eli_voice_path]
            env = os.environ.copy()
            # Keep it deterministic and GUI-friendly
            env.setdefault("PYTHONUNBUFFERED", "1")

            self.status.emit(f"voice: starting ({' '.join(cmd)})")

            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )

            if self._proc.stdout is None:
                raise RuntimeError("Popen stdout is None — check subprocess.PIPE")
            for ln in self._proc.stdout:
                if self._stop:
                    break
                self.line.emit(ln.rstrip("\n"))

            rc = self._proc.wait(timeout=2)
            self.status.emit(f"voice: stopped (rc={rc})")

        except Exception as e:
            self.error.emit(repr(e))
        finally:
            self._proc = None
