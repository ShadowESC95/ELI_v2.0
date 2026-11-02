"""In-process background task manager (multi-threaded).

For live agent work that the LLM/heuristics decide will take a while — a deep
CODE_SOLVE, a multi-component build, a self-upgrade — run it on a background
thread, return a job id immediately, and let the user check on it later.

Deliberately distinct from `eli/planning/jobqueue.py`:
  - jobqueue   = durable, SQLite-persisted *external subprocess (argv)* jobs with
                 a separate polling worker.
  - this       = lightweight *in-process* thread tasks running Python callables
                 (agent work). The record of them outlives the session: what a job was
                 given and how it ended is written to a file, so a job cut off by a restart
                 reads as cut off and "the rest of them" still means something.

Thread-safe; small integer job ids ("check job 3"); best-effort cancel.
"""

from __future__ import annotations

import json
import os
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
    status: str = "queued"          # scheduled | queued | running | done | failed | cancelled | interrupted
    created: float = field(default_factory=time.time)
    started: Optional[float] = None
    finished: Optional[float] = None
    result: Any = None
    error: str = ""
    note: str = ""                  # short human summary set by the task or on completion
    kind: str = "task"              # task | code | research | self_upgrade | reflection | action
    scheduled_for: Optional[float] = None  # unix ts when a scheduled task fires
    meta: Dict[str, Any] = field(default_factory=dict)  # display/edit metadata (request, when_spec…)
    progress: Dict[str, Any] = field(default_factory=dict)  # done, total, stage, since (report())

    def elapsed(self) -> float:
        if self.status == "scheduled":      # waiting for its time, not working: read 12069 s on "check jobs"
            return 0.0
        end = self.finished or time.time()
        start = self.started or self.created
        return max(0.0, end - start)

    def eta_s(self) -> Optional[float]:
        """Time left in the current stage at the rate measured so far in it; None before a first item."""
        p = self.progress
        done, total = int(p.get("done") or 0), int(p.get("total") or 0)
        if self.status != "running" or not done or total <= done:
            return None
        return (time.time() - float(p.get("since") or time.time())) / done * (total - done)

    def to_dict(self, *, include_result: bool = False) -> Dict[str, Any]:
        eta = self.eta_s()
        d = {
            "id": self.id, "name": self.name, "status": self.status,
            "kind": self.kind, "created": self.created, "meta": dict(self.meta or {}),
            "elapsed_s": round(self.elapsed(), 2),
            "scheduled_for": self.scheduled_for,
            "note": self.note, "error": self.error[:500],
            "progress": dict(self.progress), "eta_s": None if eta is None else round(eta, 1),
        }
        if include_result:
            d["result"] = self.result
        return d


_running = threading.local()      # the job this worker thread is running


def report(done: int, total: int, stage: str = "") -> None:
    """Progress of the job running on this thread ("reading", 120 of 354); nothing outside a job."""
    job = getattr(_running, "job", None)
    if job is not None:
        runner, jid = job
        runner.report(jid, done, total, stage)


# A finished job stays on the record this long: long enough for "what happened to those PDFs?" days later.


def _tunable(key: str) -> int:
    from eli.core.cognition_tunables import get_tunable
    return get_tunable(key)
_LEDGER_FIELDS = ("id", "name", "status", "kind", "created", "started", "finished", "note", "error", "meta",
                  "scheduled_for", "progress")


def ledger_path() -> str:
    from eli.core.paths import data_dir
    return os.path.join(str(data_dir()), "runtime", "background_jobs.json")


class BackgroundTasks:
    def __init__(self, max_workers: int = 4, ledger: Optional[str] = None):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="eli-bg")
        self._lock = threading.Lock()
        self._tasks: Dict[int, Task] = {}
        self._futures: Dict[int, Future] = {}
        self._timers: Dict[int, "threading.Timer"] = {}
        self._counter = 0
        self._ledger = ledger
        self._listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._load_ledger()

    def _load_ledger(self) -> None:
        """Jobs of earlier sessions. One that was still going when ELI closed did not finish, and
        its thread is gone: it is interrupted, not running."""
        if not self._ledger:
            return
        try:
            with open(self._ledger, encoding="utf-8") as fh:
                rows = json.load(fh)
        except FileNotFoundError:
            return
        except Exception:
            log.debug("job record unreadable", exc_info=True)
            return
        for row in rows if isinstance(rows, list) else []:
            try:
                t = Task(**{k: row[k] for k in _LEDGER_FIELDS if k in row})
            except TypeError:
                continue
            if t.status in ("queued", "running"):
                t.status, t.finished = "interrupted", t.finished or time.time()
            self._tasks[t.id] = t
            self._counter = max(self._counter, t.id)

    def _save_ledger(self) -> None:
        """Called with no lock held. Scheduled jobs are left to scheduled_tasks' own file."""
        if not self._ledger:
            return
        now = time.time()
        with self._lock:
            rows = [{k: getattr(t, k) for k in _LEDGER_FIELDS} for t in self._tasks.values()
                    if t.status != "scheduled" and now - (t.finished or now) < _tunable("cog.jobs_kept_days") * 86400]
        try:
            os.makedirs(os.path.dirname(self._ledger), exist_ok=True)
            tmp = f"{self._ledger}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, ensure_ascii=False, default=str)
            os.replace(tmp, self._ledger)
        except OSError:
            log.debug("job record not written", exc_info=True)

    def add_listener(self, fn: Callable[[Dict[str, Any]], None]) -> None:
        """`fn(job)` when a job ends, on the job's thread: how a finished job reaches the person."""
        self._listeners.append(fn)

    def _execute(self, jid: int, name: str, fn: Callable[..., Any],
                 args: tuple, kwargs: dict, on_done) -> None:
        """Shared runner used by both immediate and scheduled tasks."""
        with self._lock:
            t = self._tasks.get(jid)
            if t is None or t.status == "cancelled":
                return
            t.status = "running"
            t.started = time.time()
        self._save_ledger()
        # Mark every model call this job triggers as background so it carries the cooperative abort: a
        # foreground turn preempts it at the next token (the job's chat_completion path isn't
        # token-capped, so summaries stay full length when uninterrupted). Without this a multi-minute
        # PDF/codegen job held the model lock and foreground turns queued 200-530s behind it.
        try:
            from eli.cognition.gguf_inference import set_background_inference as _set_bg, set_job_inference
            _set_bg(True)
            set_job_inference(True)
        except Exception:
            log.debug("suppressed exception", exc_info=True)
        _running.job = (self, jid)
        try:
            res = fn(*args, **kwargs)
            with self._lock:
                t = self._tasks[jid]
                t.result = res
                t.finished = time.time()
                # A handler that reports failure did not finish the job, whatever the thread did.
                if isinstance(res, dict) and res.get("ok") is False and not res.get("skipped"):
                    t.status = "failed"
                    t.error = str(res.get("error") or res.get("content") or "it reported failure")[:500]
                else:
                    t.status = "done"
                if not t.note:
                    t.note = _summarize_result(res)
                if isinstance(res, dict) and res.get("document_path"):
                    t.meta["document_path"] = res["document_path"]
        except Exception as exc:
            with self._lock:
                t = self._tasks[jid]
                t.status = "failed"
                t.finished = time.time()
                t.error = f"{exc}\n{traceback.format_exc()[-800:]}"
            log.debug(f"[BG] task {jid} ({name}) failed: {exc}")
        finally:
            _running.job = None
            self._save_ledger()
            if on_done:
                try:
                    on_done(self._tasks.get(jid))
                except Exception:
                    log.debug("suppressed exception", exc_info=True)
            with self._lock:
                t = self._tasks.get(jid)
                ended = t.to_dict(include_result=True) if t else None
            for listener in list(self._listeners) if ended else ():
                try:
                    listener(ended)
                except Exception as exc:    # the job's own record says what did not happen after it
                    log.debug("job listener failed", exc_info=True)
                    with self._lock:
                        self._tasks[jid].meta["after_job_error"] = str(exc)[:200]
                    self._save_ledger()

    def report(self, jid: int, done: int, total: int, stage: str = "") -> None:
        with self._lock:
            t = self._tasks.get(int(jid))
            if t is None:
                return
            if t.progress.get("stage") != stage:
                t.progress = {"stage": stage, "since": time.time()}
            t.progress.update(done=int(done), total=int(total))

    def submit(self, name: str, fn: Callable[..., Any], *args,
               on_done: Optional[Callable[[Task], None]] = None,
               kind: str = "task", meta: Optional[Dict[str, Any]] = None, **kwargs) -> int:
        """Schedule `fn(*args, **kwargs)` on a background thread NOW. Returns a job id."""
        with self._lock:
            self._counter += 1
            jid = self._counter
            self._tasks[jid] = Task(id=jid, name=str(name)[:120], kind=kind, meta=dict(meta or {}))
        self._save_ledger()
        fut = self._pool.submit(self._execute, jid, name, fn, args, kwargs, on_done)
        with self._lock:
            self._futures[jid] = fut
        return jid

    def schedule(self, name: str, fn: Callable[..., Any], *args,
                 when: Optional[float] = None, delay: Optional[float] = None,
                 kind: str = "task", on_done: Optional[Callable[[Task], None]] = None,
                 meta: Optional[Dict[str, Any]] = None, **kwargs) -> int:
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
                                    status="scheduled", scheduled_for=fire_at,
                                    meta=dict(meta or {}))

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

    def list(self, *, limit: int = 20, status: Optional[str] = None,
             housekeeping: bool = False) -> List[Dict[str, Any]]:
        """Newest first. ELI's own housekeeping (kind "housekeeping") only when asked for: nobody
        asked for those, and "did the job finish?" answered about one."""
        with self._lock:
            tasks = sorted(self._tasks.values(), key=lambda t: t.id, reverse=True)
        if not housekeeping:
            tasks = [t for t in tasks if t.kind != "housekeeping"]
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
                        log.debug("suppressed exception", exc_info=True)
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
                log.debug("suppressed exception", exc_info=True)
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
            log.debug("suppressed exception", exc_info=True)


def _summarize_result(res: Any) -> str:
    if res is None:
        return ""
    try:
        if isinstance(res, dict):
            if "script_path" in res:
                return f"{'solved' if res.get('solved') else 'done'} → {res.get('script_path')}"
            if str(res.get("content") or "").strip():
                return str(res["content"]).strip().splitlines()[0][:_tunable("cog.job_line_chars")]
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
                _singleton = BackgroundTasks(ledger=ledger_path())
                _singleton.add_listener(_record_failed_job)
                _singleton.add_listener(_tell_the_person)
    return _singleton


def _job_outcome_lines(job: Dict[str, Any]) -> List[str]:
    return str(job.get("error") or job.get("note") or "").strip().splitlines()


def _record_failed_job(job: Dict[str, Any]) -> None:
    """A job that failed goes on the failure record that self-analysis reads."""
    if job["status"] != "failed":
        return
    said = _job_outcome_lines(job)
    from eli.runtime.self_improvement import get_self_improvement
    get_self_improvement().memory.log_failure(
        job["name"], error=f"background job failed: {said[0] if said else 'no reason recorded'}",
        context={"job": job["id"], "targets": (job.get("meta") or {}).get("targets")}, source="anomaly")


def _tell_the_person(job: Dict[str, Any]) -> None:
    """A job someone asked for reaches them when it ends, the way a reminder does."""
    if not (job.get("meta") or {}).get("tell") or job["status"] == "cancelled":
        return
    if os.environ.get("ELI_AGENDA_NOTIFY", "1").strip().lower() in ("0", "false", "off", "no"):
        return
    said = _job_outcome_lines(job)
    body = f"Job {job['id']} ({job['name']}) {job['status']}" + (f": {said[0][:_tunable('cog.job_line_chars')]}" if said else ".")
    from eli.utils.platform_compat import notify
    notify("ELI", body)
    from eli.planning.proactive_daemon import get_daemon
    q = getattr(get_daemon(), "suggestion_queue", None)
    if q is not None:
        q.put(("reminder", {"suggestion": body, "title": job["name"], "at": time.time()}))


def work_targets(unfinished_only: bool = False) -> List[str]:
    """The files and folders of the latest job given any, from the last day: what "them", "those"
    and "the rest" point at. `unfinished_only`: only if that job did not finish."""
    for job in get_background_tasks().list():
        targets = (job.get("meta") or {}).get("targets") or []
        if targets and time.time() - float(job.get("created") or 0) < _tunable("cog.jobs_in_hand_hours") * 3600:
            if unfinished_only and job["status"] == "done":
                return []
            return [str(t) for t in targets]
    return []


def work_lines(limit: Optional[int] = None, within_s: Optional[float] = None) -> List[str]:
    """Recent jobs as the job manager has them, newest first. Asked "where are the PDFs?" with
    nothing to go on, a model said it had none, then that the 17 it had read were made up."""
    lines = []
    for job in get_background_tasks().list(limit=limit or _tunable("cog.jobs_listed")):
        if within_s is not None and time.time() - float(job.get("created") or 0) > within_s:
            continue
        line = f"#{job['id']} {job['name']}: {job['status']}"
        if job["status"] == "running":
            p = job.get("progress") or {}
            if p.get("total"):
                line += f" ({p.get('stage') or 'working'} {p.get('done', 0)} of {p['total']})"
        elif job["status"] == "scheduled" and job.get("scheduled_for"):
            line += time.strftime(" for %a %H:%M", time.localtime(float(job["scheduled_for"])))
        else:
            if job.get("finished"):
                line += time.strftime(" at %H:%M on %d %B", time.localtime(float(job["finished"])))
            saved = (job.get("meta") or {}).get("document_path")
            said = str(job.get("error") or job.get("note") or "").strip().splitlines()
            if said:
                line += f": {said[0][:_tunable('cog.job_line_chars')]}"
            if saved:
                line += f"; saved as {saved}"
        targets = (job.get("meta") or {}).get("targets") or []
        if len(targets) > 1 or (targets and str(targets[0]) not in job["name"]):
            line += "; given: " + ", ".join(str(t) for t in targets)
        lines.append(line)
    return lines


def latest_report() -> str:
    """What the last finished job came back with, as much of it as a prompt should carry."""
    for job in get_background_tasks().list(limit=1, status="done"):
        full = get_background_tasks().get(job["id"], include_result=True) or {}
        res = full.get("result")
        text = str((res.get("content") or res.get("response") or "") if isinstance(res, dict) else "").strip()
        return text[:_tunable("cog.job_report_chars")]
    return ""


def work_block(limit: Optional[int] = None) -> str:
    """The record, for a reply that may be asked about the work. Empty with no jobs."""
    lines = work_lines(limit or _tunable("cog.jobs_in_prompt"), within_s=_tunable("cog.jobs_in_prompt_days") * 86400)
    if not lines:
        return ""
    return ("Background jobs on record, written by the job manager and not by you. What is started, running, done "
            "or failed is what these lines say; nothing else has been started, and you start nothing by saying "
            "so.\n" + "\n".join(lines))
