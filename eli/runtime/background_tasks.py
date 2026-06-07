"""In-process background task manager (multi-threaded).

For live agent work that the LLM/heuristics decide will take a while — a deep
CODE_SOLVE, a multi-component build, a self-upgrade — run it on a background
thread, return a job id immediately, and let the user check on it later.

Deliberately distinct from `eli/planning/jobqueue.py`:
  - jobqueue   = durable, SQLite-persisted *external subprocess (argv)* jobs with
                 a separate polling worker.
  - this       = lightweight *in-process* thread tasks running Python callables
                 (agent work), tracked for the session.

Thread-safe; small integer job ids ("check job 3"); best-effort cancel.
"""

from __future__ import annotations

import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)


@dataclass
class Task:
    id: int
    name: str
    status: str = "queued"          # scheduled | queued | running | done | failed | cancelled
    created: float = field(default_factory=time.time)
    started: Optional[float] = None
    finished: Optional[float] = None
    result: Any = None
    error: str = ""
    note: str = ""                  # short human summary set by the task or on completion
    kind: str = "task"              # task | code | research | self_upgrade | reflection | action
    scheduled_for: Optional[float] = None  # unix ts when a scheduled task fires

    def elapsed(self) -> float:
        end = self.finished or time.time()
        start = self.started or self.created
        return max(0.0, end - start)

    def to_dict(self, *, include_result: bool = False) -> Dict[str, Any]:
        d = {
            "id": self.id, "name": self.name, "status": self.status,
            "kind": self.kind, "created": self.created,
            "elapsed_s": round(self.elapsed(), 2),
            "scheduled_for": self.scheduled_for,
            "note": self.note, "error": self.error[:500],
        }
        if include_result:
            d["result"] = self.result
        return d


class BackgroundTasks:
    def __init__(self, max_workers: int = 4):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="eli-bg")
        self._lock = threading.Lock()
        self._tasks: Dict[int, Task] = {}
        self._futures: Dict[int, Future] = {}
        self._timers: Dict[int, "threading.Timer"] = {}
        self._counter = 0

    def _execute(self, jid: int, name: str, fn: Callable[..., Any],
                 args: tuple, kwargs: dict, on_done) -> None:
        """Shared runner used by both immediate and scheduled tasks."""
        with self._lock:
            t = self._tasks.get(jid)
            if t is None or t.status == "cancelled":
                return
            t.status = "running"
            t.started = time.time()
        try:
            res = fn(*args, **kwargs)
            with self._lock:
                t = self._tasks[jid]
                t.result = res
                t.status = "done"
                t.finished = time.time()
                if not t.note:
                    t.note = _summarize_result(res)
        except Exception as exc:
            with self._lock:
                t = self._tasks[jid]
                t.status = "failed"
                t.finished = time.time()
                t.error = f"{exc}\n{traceback.format_exc()[-800:]}"
            log.debug(f"[BG] task {jid} ({name}) failed: {exc}")
        finally:
            if on_done:
                try:
                    on_done(self._tasks.get(jid))
                except Exception:
                    pass

    def submit(self, name: str, fn: Callable[..., Any], *args,
               on_done: Optional[Callable[[Task], None]] = None,
               kind: str = "task", **kwargs) -> int:
        """Schedule `fn(*args, **kwargs)` on a background thread NOW. Returns a job id."""
        with self._lock:
            self._counter += 1
            jid = self._counter
            self._tasks[jid] = Task(id=jid, name=str(name)[:120], kind=kind)
        fut = self._pool.submit(self._execute, jid, name, fn, args, kwargs, on_done)
        with self._lock:
            self._futures[jid] = fut
        return jid

    def schedule(self, name: str, fn: Callable[..., Any], *args,
                 when: Optional[float] = None, delay: Optional[float] = None,
                 kind: str = "task", on_done: Optional[Callable[[Task], None]] = None,
                 **kwargs) -> int:
        """Schedule `fn` to run at unix time `when` (or after `delay` seconds) — e.g.
        an overnight job. Shows as 'scheduled' until its time, then runs like submit().
        Returns a job id. (In-process: requires ELI to be running at the fire time;
        a cancelled scheduled task never fires.)"""
        now = time.time()
        fire_at = float(when) if when is not None else now + float(delay or 0.0)
        with self._lock:
            self._counter += 1
            jid = self._counter
            self._tasks[jid] = Task(id=jid, name=str(name)[:120], kind=kind,
                                    status="scheduled", scheduled_for=fire_at)

        def _fire():
            with self._lock:
                self._timers.pop(jid, None)
                t = self._tasks.get(jid)
                if t is None or t.status == "cancelled":
                    return
            fut = self._pool.submit(self._execute, jid, name, fn, args, kwargs, on_done)
            with self._lock:
                self._futures[jid] = fut

        timer = threading.Timer(max(0.0, fire_at - now), _fire)
        timer.daemon = True
        with self._lock:
            self._timers[jid] = timer
        timer.start()
        log.debug(f"[BG] scheduled task {jid} ({name}) for +{max(0.0, fire_at - now):.0f}s ({kind})")
        return jid

    def get(self, jid: int, *, include_result: bool = True) -> Optional[Dict[str, Any]]:
        with self._lock:
            t = self._tasks.get(int(jid))
            return t.to_dict(include_result=include_result) if t else None

    def list(self, *, limit: int = 20, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            tasks = sorted(self._tasks.values(), key=lambda t: t.id, reverse=True)
        if status:
            tasks = [t for t in tasks if t.status == status]
        return [t.to_dict() for t in tasks[:limit]]

    def cancel(self, jid: int) -> bool:
        """Best-effort cancel. Threads already running can't be force-killed, but a
        queued task is cancelled and a running one is marked for the runner to skip."""
        with self._lock:
            t = self._tasks.get(int(jid))
            fut = self._futures.get(int(jid))
            timer = self._timers.pop(int(jid), None)
            if t is None:
                return False
            if t.status in ("done", "failed", "cancelled"):
                return False
            # A scheduled task that hasn't fired: cancel its timer outright.
            if t.status == "scheduled":
                if timer is not None:
                    try:
                        timer.cancel()
                    except Exception:
                        pass
                t.status = "cancelled"
                t.finished = time.time()
                return True
            cancelled = fut.cancel() if fut else False
            if cancelled or t.status == "queued":
                t.status = "cancelled"
                t.finished = time.time()
                return True
            # running: mark; cooperative tasks may observe this via get()
            t.note = (t.note + " | cancel requested").strip(" |")
            return False

    def wait(self, jid: int, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Block until a task finishes (used by tests / synchronous callers)."""
        fut = None
        with self._lock:
            fut = self._futures.get(int(jid))
        if fut is not None:
            try:
                fut.result(timeout=timeout)
            except Exception:
                pass
        return self.get(jid)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            tasks = list(self._tasks.values())
        by = {}
        for t in tasks:
            by[t.status] = by.get(t.status, 0) + 1
        return {"total": len(tasks), "by_status": by}

    def shutdown(self) -> None:
        try:
            self._pool.shutdown(wait=False)
        except Exception:
            pass


def _summarize_result(res: Any) -> str:
    try:
        if isinstance(res, dict):
            if "script_path" in res:
                return f"{'solved' if res.get('solved') else 'done'} → {res.get('script_path')}"
            if "ok" in res:
                return f"ok={res.get('ok')}"
        return str(res)[:120]
    except Exception:
        return "done"


_singleton: Optional[BackgroundTasks] = None
_singleton_lock = threading.Lock()


def get_background_tasks() -> BackgroundTasks:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = BackgroundTasks()
    return _singleton
