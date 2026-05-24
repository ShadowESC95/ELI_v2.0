from __future__ import annotations

import threading
import time
from typing import Optional

from eli.plugins.base.base import Plugin



from eli.utils.log import get_logger
log = get_logger(__name__)

class PomodoroTimerPlugin(Plugin):
    name = "pomodoro"
    description = "Focus sessions with Pomodoro technique"

    WORK_MINS = 25
    BREAK_MINS = 5

    def __init__(self):
        self._timer: Optional[threading.Timer] = None
        self._start_time: float = 0.0
        self._duration_secs: int = 0
        self._session_type: str = ""
        self._session_count: int = 0
        self.actions = {
            "start": self.start,
            "stop": self.stop,
            "status": self.status,
        }
        super().__init__()

    def start(self, args: dict) -> dict:
        session = args.get("type", args.get("session", "work"))
        default_mins = self.BREAK_MINS if session == "break" else self.WORK_MINS
        duration = int(args.get("minutes", args.get("duration", default_mins))) * 60

        if self._timer and self._timer.is_alive():
            self._timer.cancel()

        self._start_time = time.time()
        self._duration_secs = duration
        self._session_type = session
        self._session_count += 1

        self._timer = threading.Timer(duration, self._on_complete, args=(session,))
        self._timer.daemon = True
        self._timer.start()

        mins = duration // 60
        msg = f"Pomodoro started: {mins}-min {session} session (#{self._session_count}). I'll notify you when it's done."
        return {"ok": True, "content": msg, "response": msg,
                "session": session, "minutes": mins, "count": self._session_count}

    def stop(self, args: dict) -> dict:
        if self._timer and self._timer.is_alive():
            self._timer.cancel()
            elapsed = int(time.time() - self._start_time)
            m, s = elapsed // 60, elapsed % 60
            msg = f"Pomodoro stopped after {m}m {s}s of {self._session_type} session."
            self._session_type = ""
            return {"ok": True, "content": msg, "response": msg}
        return {"ok": False, "content": "No active Pomodoro timer.", "response": "No active Pomodoro timer."}

    def status(self, args: dict) -> dict:
        if not self._session_type or not (self._timer and self._timer.is_alive()):
            msg = f"No active Pomodoro session. Completed sessions: {self._session_count}."
            return {"ok": True, "content": msg, "response": msg, "active": False}
        elapsed = int(time.time() - self._start_time)
        remaining = max(0, self._duration_secs - elapsed)
        rm, rs = remaining // 60, remaining % 60
        em = elapsed // 60
        msg = (
            f"Pomodoro: {self._session_type} session — "
            f"{rm}m {rs}s remaining ({em}m elapsed). "
            f"Session #{self._session_count}."
        )
        return {
            "ok": True, "content": msg, "response": msg,
            "active": True, "remaining_secs": remaining,
            "elapsed_secs": elapsed, "session": self._session_type,
        }

    def _on_complete(self, session: str) -> None:
        self._session_type = ""
        log.debug(f"[POMODORO] {session.capitalize()} session complete! Take a {'break' if session == 'work' else 'look at your work'}.")
        try:
            from eli.perception.tts_router import maybe_speak
            maybe_speak(f"Pomodoro {session} session complete!", enabled=True)
        except Exception:
            pass
