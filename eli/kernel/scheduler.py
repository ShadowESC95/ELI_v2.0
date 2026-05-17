"""
MKXI kernel-local scheduler compatibility layer.

Why this exists:
- eli.kernel.engine imports `from .scheduler import get_scheduler`
- the migration-generated shim forwarded into eli.planning.scheduler
- eli.planning.scheduler is a consolidation stub and intentionally raises

This file restores a concrete kernel-owned scheduler contract so engine imports
do not depend on deprecated placeholder modules.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import RLock, Timer
from typing import Any, Callable


@dataclass
class KernelScheduler:
    max_workers: int = 4
    _executor: ThreadPoolExecutor = field(init=False)
    _timers: list[Timer] = field(default_factory=list)
    _lock: RLock = field(default_factory=RLock)

    def __post_init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(self.max_workers)),
            thread_name_prefix="eli-mkxi-scheduler",
        )

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        return self._executor.submit(fn, *args, **kwargs)

    def enqueue(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        return self.submit(fn, *args, **kwargs)

    def run_now(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        return self.submit(fn, *args, **kwargs)

    def schedule(self, delay: float, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Timer:
        timer = Timer(max(0.0, float(delay)), fn, args=args, kwargs=kwargs)
        timer.daemon = True
        with self._lock:
            self._timers.append(timer)
        timer.start()
        return timer

    def call_later(self, delay: float, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Timer:
        return self.schedule(delay, fn, *args, **kwargs)

    def shutdown(self, wait: bool = False, cancel_futures: bool = False) -> None:
        with self._lock:
            for timer in self._timers:
                try:
                    timer.cancel()
                except Exception:
                    pass
            self._timers.clear()
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)


_scheduler_singleton: KernelScheduler | None = None
_scheduler_lock = RLock()


def get_scheduler() -> KernelScheduler:
    global _scheduler_singleton
    with _scheduler_lock:
        if _scheduler_singleton is None:
            _scheduler_singleton = KernelScheduler()
        return _scheduler_singleton
