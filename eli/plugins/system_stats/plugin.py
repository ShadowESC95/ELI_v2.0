from __future__ import annotations
from eli.plugins.base.base import Plugin

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


class SystemStatsPlugin(Plugin):
    name = "system_stats"
    description = "CPU, RAM, disk, network monitoring"

    def __init__(self):
        self.actions = {
            "system_stats": self.system_stats,
            "cpu_usage": self.cpu_usage,
            "ram_usage": self.ram_usage,
        }
        super().__init__()

    def system_stats(self, args: dict) -> dict:
        if not _HAS_PSUTIL:
            return self._fallback_stats()
        cpu = _psutil.cpu_percent(interval=0.5)
        mem = _psutil.virtual_memory()
        disk = _psutil.disk_usage("/")
        msg = (
            f"CPU: {cpu:.1f}%  |  "
            f"RAM: {mem.percent:.1f}% ({mem.used/1e9:.1f}/{mem.total/1e9:.1f} GB)  |  "
            f"Disk: {disk.percent:.1f}% ({disk.used/1e9:.0f}/{disk.total/1e9:.0f} GB)"
        )
        return {
            "ok": True, "content": msg, "response": msg,
            "cpu_percent": cpu, "ram_percent": mem.percent,
            "disk_percent": disk.percent,
        }

    def cpu_usage(self, args: dict) -> dict:
        if not _HAS_PSUTIL:
            return self._fallback_stats()
        percpu = _psutil.cpu_percent(interval=0.5, percpu=True)
        avg = sum(percpu) / len(percpu)
        core_str = ", ".join(f"{c:.0f}%" for c in percpu[:8])
        suffix = "…" if len(percpu) > 8 else ""
        msg = f"CPU: {avg:.1f}% avg  [{core_str}{suffix}]"
        return {"ok": True, "content": msg, "response": msg, "avg": avg, "per_core": percpu}

    def ram_usage(self, args: dict) -> dict:
        if not _HAS_PSUTIL:
            return self._fallback_stats()
        mem = _psutil.virtual_memory()
        swap = _psutil.swap_memory()
        msg = (
            f"RAM: {mem.used/1e9:.1f}/{mem.total/1e9:.1f} GB ({mem.percent:.1f}%)  |  "
            f"Swap: {swap.used/1e9:.1f}/{swap.total/1e9:.1f} GB ({swap.percent:.1f}%)"
        )
        return {
            "ok": True, "content": msg, "response": msg,
            "ram_percent": mem.percent, "swap_percent": swap.percent,
        }

    def _fallback_stats(self) -> dict:
        import subprocess, re
        try:
            out = subprocess.check_output(["free", "-m"], text=True)
            lines = out.strip().splitlines()
            parts = lines[1].split()
            total_mb, used_mb = int(parts[1]), int(parts[2])
            msg = f"RAM: {used_mb} / {total_mb} MB  (psutil not installed — install for full stats)"
        except Exception:
            msg = "System stats unavailable. Install psutil: pip install psutil"
        return {"ok": True, "content": msg, "response": msg}
