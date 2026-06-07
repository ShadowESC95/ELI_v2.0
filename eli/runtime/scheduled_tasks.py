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
    if re.search(r"\b(train|run)\s+(a\s+|the\s+)?lora\b|\blora\s+train(ing)?\b|"
                 r"\bfine[- ]?tune\b|\btrain\s+(an?\s+)?adapter\b", r):
        return "lora"
    if re.search(r"\b(generate|write|create)\s+(behaviou?ral\s+|unit\s+)?tests?\b|"
                 r"\btest\s+generation\b|\bgrow\s+(test\s+)?coverage\b", r):
        return "testgen"
    if re.search(r"\b(engine[- ]?eval|run (?:the )?eval|evaluate yourself|eval (?:harness|board)|"
                 r"run (?:the )?test suite|run (?:your|the) tests|self[- ]?test report)\b", r):
        return "eval"
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


def _worker_eval(request: str):
    """Overnight engine eval + full test report → populate the boards.
    Runs the model-backed engine eval cases and the test-report generator, writing
    artifacts/eval/engine_eval_results.json and artifacts/test_report.md."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _P
    repo = _P(__file__).resolve().parents[2]
    out = {"ok": True}
    try:
        evdir = repo / "artifacts" / "eval"
        evdir.mkdir(parents=True, exist_ok=True)
        res_json = evdir / "engine_eval_results.json"
        r = subprocess.run(
            [_sys.executable, "tools/eval/run_eval.py", "--target", "engine",
             "--json", str(res_json)],
            cwd=str(repo), capture_output=True, text=True, timeout=3600)
        out["engine_eval"] = (r.stdout or r.stderr or "")[-1200:]
        out["engine_results_path"] = str(res_json)
        out["engine_ok"] = (r.returncode == 0)
    except Exception as e:
        out["ok"] = False
        out["engine_error"] = str(e)
    try:
        # full test report (writes artifacts/test_report.md via the conftest hook)
        tr = subprocess.run(
            [_sys.executable, "tools/run_test_report.py", "tests/"],
            cwd=str(repo), capture_output=True, text=True, timeout=3600)
        out["test_report"] = (tr.stdout or "")[-600:]
        out["test_report_path"] = str(repo / "artifacts" / "test_report.md")
    except Exception as e:
        out["test_report_error"] = str(e)
    return out


def _worker_testgen(request: str):
    """Overnight ELI-assisted test generation: write + sandbox-verify behavioural
    tests for untested functions; only passing ones land in tests/generated/."""
    try:
        from eli.runtime.test_generator import run_testgen
        m = re.search(r"(\d+)", request or "")
        limit = min(int(m.group(1)), 25) if m else 8
        return {"ok": True, "testgen": run_testgen(limit=limit)}
    except Exception as e:
        return {"ok": False, "error": f"test generation failed: {e}"}


def _worker_lora(request: str):
    """Overnight LoRA fine-tune via the pipeline DAG (preflight→build→train→eval),
    execute=True. Still bound by the trainer's safety contract (reviewed rows only,
    GGUF never trained, adapter never overwritten)."""
    try:
        from eli.learning.lora_pipeline import run_pipeline
        m = re.search(r"(\d+)\s*steps?", request or "")
        steps = min(int(m.group(1)), 2000) if m else 50
        return {"ok": True, "lora": run_pipeline("eli_phi", execute=True, max_steps=steps)}
    except Exception as e:
        return {"ok": False, "error": f"lora training failed: {e}"}


_WORKERS = {
    "code": _worker_code,
    "research": _worker_research,
    "self_upgrade": _worker_self_upgrade,
    "reflection": _worker_reflection,
    "eval": _worker_eval,
    "testgen": _worker_testgen,
    "lora": _worker_lora,
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
    if kind == "eval":
        return (f"engine eval {'ok' if res.get('engine_ok') else 'ran'}; "
                f"{str(res.get('test_report') or '').strip()[:300]}")
    if kind == "testgen":
        tg = res.get("testgen") or {}
        return (f"generated {tg.get('accepted', 0)} test(s), rejected "
                f"{tg.get('rejected', 0)} of {tg.get('targets', 0)} targets")
    if kind == "lora":
        lr = res.get("lora") or {}
        return str(lr.get("summary") or lr)[:400]
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
         catchup: bool = False, project: str = "", recurring: bool = False) -> int:
    """Create the in-process timed job. on_done removes the persisted entry, surfaces
    the result, and (when recurring) re-schedules for the next occurrence — so a
    'overnight' task repeats nightly (when_spec re-resolves to the next 02:00)."""
    from eli.runtime.background_tasks import get_background_tasks
    worker = _WORKERS.get(kind, _worker_research)
    surface = _surface(request + (" (catch-up: missed while offline)" if catchup else ""), kind)

    def _on_done(task) -> None:
        forget(pid)
        try:
            surface(task)
        except Exception:
            pass
        if recurring:
            try:
                schedule_request(request, when_spec=when_spec, kind=kind, recurring=True)
            except Exception as _rec_err:
                log.debug(f"[SCHEDULED] recurring re-arm failed: {_rec_err}")

    meta = {"request": request, "when_spec": when_spec, "kind": kind, "pid": pid,
            "recurring": bool(recurring)}
    if project:
        meta["project"] = project  # Phase 3: the project that owns this task
    return get_background_tasks().schedule(
        f"{kind}: {request[:50]}", worker, request,
        when=when_ts, kind=kind, on_done=_on_done, meta=meta,
    )


# ── Public API ───────────────────────────────────────────────────────────────
def schedule_request(request: str, when_spec: str = "", kind: Optional[str] = None,
                     recurring: bool = False) -> Dict[str, Any]:
    """Schedule a heavy task to run at a parsed time. Persisted so it survives a
    restart. recurring=True re-arms for the next occurrence after each run (nightly
    for an 'overnight' when_spec). Returns {ok, job_id, kind, when_ts, when_human, pid}."""
    request = (request or "").strip()
    if not request:
        return {"ok": False, "error": "no task description"}
    kind = (kind or infer_kind(request)).strip().lower()
    when_spec = when_spec or request
    fire_at = parse_when(when_spec)
    pid = uuid.uuid4().hex[:12]

    # Phase 3: if a project is active, it owns this task.
    project = ""
    try:
        from eli.runtime.active_project import active_name
        project = active_name()
    except Exception:
        project = ""

    try:
        _persist_add({"pid": pid, "request": request, "when_spec": when_spec,
                      "kind": kind, "when_ts": fire_at, "created": time.time(),
                      "project": project, "recurring": bool(recurring)})
        jid = _arm(pid, request, fire_at, when_spec, kind, project=project,
                   recurring=bool(recurring))
    except Exception as e:
        forget(pid)
        return {"ok": False, "error": f"schedule failed: {e}"}

    when_human = datetime.fromtimestamp(fire_at).strftime("%H:%M on %a %d %b")
    return {"ok": True, "job_id": jid, "kind": kind, "when_ts": fire_at,
            "when_human": when_human, "pid": pid, "project": project}


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
                 catchup=catchup, project=str(e.get("project") or ""),
                 recurring=bool(e.get("recurring")))
            restored += 1
        except Exception as ex:
            log.debug(f"[SCHEDULED] restore of {e.get('pid')} failed: {ex}")
    if restored:
        log.info(f"[SCHEDULED] restored {restored} scheduled task(s) from disk")
    return restored


__all__ = ["schedule_request", "parse_when", "infer_kind",
           "restore_scheduled_tasks", "forget"]
