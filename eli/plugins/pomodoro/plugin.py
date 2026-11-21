from __future__ import annotations

from eli.plugins.base.base import Plugin


class PomodoroTimerPlugin(Plugin):
    """The pomodoro plugin's actions are ELI's own POMODORO_START / POMODORO_STOP / POMODORO_STATUS.

    It kept its own timer, which announced the end of a session, but the executor answers those
    actions first, so the timer never ran and no end was ever announced. There is one Pomodoro now:
    the executor's, whose end is an agenda reminder (announced like any reminder, also after a
    restart). A session can be a "work" or a "break" one ({"type": "break"})."""
    name = "pomodoro"
    description = "Focus sessions with Pomodoro technique"

    def __init__(self):
        self.actions = {
            "start": self.start,
            "stop": self.stop,
            "status": self.status,
        }
        super().__init__()

    @staticmethod
    def _action(action: str, args: dict) -> dict:
        from eli.execution.executor_enhanced import execute
        return execute(action, dict(args or {}))

    def start(self, args: dict) -> dict:
        return self._action("POMODORO_START", args)

    def stop(self, args: dict) -> dict:
        return self._action("POMODORO_STOP", args)

    def status(self, args: dict) -> dict:
        return self._action("POMODORO_STATUS", args)
