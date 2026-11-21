from __future__ import annotations

from eli.plugins.base.base import Plugin


class SystemStatsPlugin(Plugin):
    """The system-stats plugin's actions are ELI's own SYSTEM_STATS / CPU_USAGE / RAM_USAGE.

    It kept a second, smaller copy of those readings, which never ran: the executor answers these
    actions first. One implementation now, the executor's (CPU frequency and temperature, battery,
    and a stated failure when psutil, which ELI needs, is missing)."""
    name = "system_stats"
    description = "CPU, RAM, disk, network monitoring"

    def __init__(self):
        self.actions = {
            "system_stats": self.system_stats,
            "cpu_usage": self.cpu_usage,
            "ram_usage": self.ram_usage,
        }
        super().__init__()

    @staticmethod
    def _action(action: str, args: dict) -> dict:
        from eli.execution.executor_enhanced import execute
        return execute(action, dict(args or {}))

    def system_stats(self, args: dict) -> dict:
        return self._action("SYSTEM_STATS", args)

    def cpu_usage(self, args: dict) -> dict:
        return self._action("CPU_USAGE", args)

    def ram_usage(self, args: dict) -> dict:
        return self._action("RAM_USAGE", args)
