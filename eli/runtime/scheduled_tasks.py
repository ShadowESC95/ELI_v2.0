"""Scheduled / overnight advanced tasks.

Turns a request like "design me a new element overnight", "build X at 2am",
"research Y in 3 hours", or "run a self-upgrade tonight" into a timed background
job that runs the *right kind* of heavy work at the requested time and surfaces
the result (Proactive panel + the Tasks tab):

  • code        → the verified coding agent (eli.coding.solve)
  • research    → a deep reasoning pass (engine at Research mode)
  • self_upgrade→ the self-upgrade orchestrator
  • reflection  → the reflection engine

Built on `background_tasks.schedule()`. In-process: ELI must be running at the
fire time (it runs overnight); a cancelled job never fires.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

_OVERNIGHT_HOUR = 2  # "overnight"/"tonight" → next 02:00
_CATCHUP_DELAY = 30.0  # missed-while-off tasks run this many seconds after boot
_STORE_LOCK = threading.RLock()
_RESTORED = False


# ── Durable store (survives restarts) ────────────────────────────────────────
def _store_path() -> Path:
    try:
        from eli.core.paths import get_paths
        base = get_paths().artifacts_dir / "runtime"
    except Exception:
        base = Path(__file__).resolve().parents[2] / "artifacts" / "runtime"
    base.mkdir(parents=True, exist_ok=True)
    return base / "scheduled_tasks.json"


def _load_store() -> List[Dict[str, Any]]:
    p = _store_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except Exception:
        return []


def _save_store(entries: List[Dict[str, Any]]) -> None:
    try:
        _store_path().write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except Exception as e:
        log.debug(f"[SCHEDULED] store save failed: {e}")


def _persist_add(entry: Dict[str, Any]) -> None:
    with _STORE_LOCK:
        entries = _load_store()
        entries.append(entry)
        _save_store(entries)


def forget(pid: str) -> None:
    """Drop a persisted scheduled task (on completion or cancel) so it doesn't
    re-arm on the next boot."""
    if not pid:
        return
    with _STORE_LOCK:
        entries = [e for e in _load_store() if e.get("pid") != pid]
        _save_store(entries)


# ── Time parsing ─────────────────────────────────────────────────────────────
def parse_when(text: str) -> float:
    """Return a unix timestamp for when to run, parsed from natural language.
    Defaults to the next 02:00 (overnight) when no explicit time is found."""
    t = (text or "").lower()
    now = datetime.now()

    m = re.search(r"\bin\s+(\d+)\s*(hour|hr|minute|min)s?\b", t)
    if m:
        n = int(m.group(1))
        delta = timedelta(hours=n) if m.group(2).startswith(("hour", "hr")) else timedelta(minutes=n)
        return (now + delta).timestamp()

    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", t)
    if m:
        hh = int(m.group(1)) % 24
        mm = int(m.group(2) or 0)
        ap = m.group(3)
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target.timestamp()

    if "tomorrow" in t:
        hh = 2 if ("overnight" in t or "tonight" in t) else 9
        return (now + timedelta(days=1)).replace(hour=hh, minute=0, second=0, microsecond=0).timestamp()

    # overnight / tonight / default → next 02:00
    target = now.replace(hour=_OVERNIGHT_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target.timestamp()


# ── Kind inference ───────────────────────────────────────────────────────────
def infer_kind(request: str) -> str:
    r = (request or "").lower()
    if re.search(r"\b(self[- ]?upgrade|update yourself|upgrade yourself)\b", r):
        return "self_upgrade"
    if re.search(r"\b(reflect|reflection|review (?:my|the) (?:day|session))\b", r):
        return "reflection"
    if re.search(r"\b(code|script|program|implement|build (?:a|an|the)?\s*(?:app|tool|function|class)|write (?:a|the)?\s*(?:script|program|function)|refactor|debug)\b", r):
        return "code"
    # design/research/analyse/investigate/report/"design me a new …" → deep reasoning
    return "research"


# ── Workers (run inside the background thread at fire time) ───────────────────
def _worker_code(request: str):
    try:
        from eli.coding import solve
        return solve(request)
    except Exception as e:
        return {"ok": False, "error": f"coding agent failed: {e}"}


def _worker_research(request: str):
    try:
        from eli.kernel.engine import get_engine
        eng = get_engine()
        if eng is None:
            return {"ok": False, "error": "engine unavailable"}
        res = eng.process(request, source="scheduled_task", reasoning_mode="research")
        text = res.get("response") or res.get("content") if isinstance(res, dict) else str(res)
        return {"ok": True, "answer": str(text or "")}
    except Exception as e:
        return {"ok": False, "error": f"research task failed: {e}"}


def _worker_self_upgrade(request: str):
    try:
        from eli.kernel.self_upgrade import SelfUpgrader
        return {"ok": True, "report": SelfUpgrader().upgrade(request)}
    except Exception as e:
        return {"ok": False, "error": f"self-upgrade failed: {e}"}


def _worker_reflection(request: str):
    try:
        from eli.runtime.reflection import run_reflection
        return {"ok": True, "reflection": run_reflection(hours=24)}
    except Exception as e:
        return {"ok": False, "error": f"reflection failed: {e}"}


_WORKERS = {
    "code": _worker_code,
    "research": _worker_research,
    "self_upgrade": _worker_self_upgrade,
    "reflection": _worker_reflection,
}


def _result_preview(kind: str, res: Any) -> str:
    if not isinstance(res, dict):
        return str(res)[:300]
    if res.get("error"):
        return f"failed: {res['error']}"
    if kind == "code":
        return f"built → {res.get('script_path') or res.get('path') or 'done'}"
    if kind == "research":
        return str(res.get("answer") or "")[:600]
    if kind == "self_upgrade":
        return str(res.get("report") or "")[:600]
    if kind == "reflection":
        return str(res.get("reflection") or "")[:600]
    return str(res)[:300]


def _surface(request: str, kind: str):
    """Return an on_done callback that posts the finished result to the Proactive panel."""
    def _cb(task) -> None:
        try:
            res = getattr(task, "result", None)
            note = (f"Overnight {kind} task done — “{request[:70]}”:\n\n"
                    f"{_result_preview(kind, res)}")
            from eli.planning.proactive_daemon import get_daemon
            d = get_daemon()
            q = getattr(d, "suggestion_queue", None) if d is not None else None
            if q is not None:
                q.put(("scheduled_task_done", {"suggestion": note, "request": request, "kind": kind}))
        except Exception as e:
            log.debug(f"[SCHEDULED] surface failed: {e}")
    return _cb


# ── Arming (shared by new schedules + boot restore) ──────────────────────────
def _arm(pid: str, request: str, when_ts: float, when_spec: str, kind: str,
         catchup: bool = False) -> int:
    """Create the in-process timed job. on_done both removes the persisted entry
    (no longer pending) and surfaces the result."""
    from eli.runtime.background_tasks import get_background_tasks
    worker = _WORKERS.get(kind, _worker_research)
    surface = _surface(request + (" (catch-up: missed while offline)" if catchup else ""), kind)

    def _on_done(task) -> None:
        forget(pid)
        try:
            surface(task)
        except Exception:
            pass

    return get_background_tasks().schedule(
        f"{kind}: {request[:50]}", worker, request,
        when=when_ts, kind=kind, on_done=_on_done,
        meta={"request": request, "when_spec": when_spec, "kind": kind, "pid": pid},
    )


# ── Public API ───────────────────────────────────────────────────────────────
def schedule_request(request: str, when_spec: str = "", kind: Optional[str] = None) -> Dict[str, Any]:
    """Schedule a heavy task to run at a parsed time. Persisted so it survives a
    restart. Returns {ok, job_id, kind, when_ts, when_human, pid}."""
    request = (request or "").strip()
    if not request:
        return {"ok": False, "error": "no task description"}
    kind = (kind or infer_kind(request)).strip().lower()
    when_spec = when_spec or request
    fire_at = parse_when(when_spec)
    pid = uuid.uuid4().hex[:12]

    try:
        _persist_add({"pid": pid, "request": request, "when_spec": when_spec,
                      "kind": kind, "when_ts": fire_at, "created": time.time()})
        jid = _arm(pid, request, fire_at, when_spec, kind)
    except Exception as e:
        forget(pid)
        return {"ok": False, "error": f"schedule failed: {e}"}

    when_human = datetime.fromtimestamp(fire_at).strftime("%H:%M on %a %d %b")
    return {"ok": True, "job_id": jid, "kind": kind, "when_ts": fire_at,
            "when_human": when_human, "pid": pid}


def restore_scheduled_tasks() -> int:
    """Re-arm persisted scheduled tasks on boot. Future ones fire at their time;
    tasks missed while ELI was off run shortly after boot (catch-up). Idempotent."""
    global _RESTORED
    with _STORE_LOCK:
        if _RESTORED:
            return 0
        _RESTORED = True
        entries = _load_store()
    now = time.time()
    restored = 0
    for e in entries:
        try:
            wt = float(e.get("when_ts") or 0)
            catchup = wt <= now
            if catchup:
                wt = now + _CATCHUP_DELAY
            _arm(str(e.get("pid") or uuid.uuid4().hex[:12]),
                 str(e.get("request") or ""), wt,
                 str(e.get("when_spec") or ""), str(e.get("kind") or "research"),
                 catchup=catchup)
            restored += 1
        except Exception as ex:
            log.debug(f"[SCHEDULED] restore of {e.get('pid')} failed: {ex}")
    if restored:
        log.info(f"[SCHEDULED] restored {restored} scheduled task(s) from disk")
    return restored


__all__ = ["schedule_request", "parse_when", "infer_kind",
           "restore_scheduled_tasks", "forget"]
