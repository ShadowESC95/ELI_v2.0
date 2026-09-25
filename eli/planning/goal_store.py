from __future__ import annotations

import json
import re
import os
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

from eli.planning.goal_models import GoalSpec


def _default_goal_store() -> Path:
    env = os.environ.get("ELI_GOAL_STORE", "").strip()
    if env:
        return Path(env).expanduser()
    return Path("artifacts/runtime/goals.json")


def goal_store_path() -> Path:
    path = _default_goal_store()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def load_goals() -> List[GoalSpec]:
    path = goal_store_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = raw if isinstance(raw, list) else raw.get("goals", [])
    return [GoalSpec.from_any(x) for x in items if isinstance(x, dict)]


def save_goals(goals: List[GoalSpec]) -> Path:
    path = goal_store_path()
    payload = [g.to_dict() for g in goals]
    _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def upsert_goal(goal: Dict[str, Any] | GoalSpec) -> GoalSpec:
    goals = load_goals()
    spec = GoalSpec.from_any(goal)
    now = time.time()
    spec.updated_at = now
    replaced = False
    for i, cur in enumerate(goals):
        if cur.goal_id == spec.goal_id:
            spec.created_at = cur.created_at
            goals[i] = spec
            replaced = True
            break
    if not replaced:
        if not spec.created_at:
            spec.created_at = now
        goals.append(spec)
    save_goals(goals)
    return spec


def list_active_goals() -> List[GoalSpec]:
    return [
        g for g in load_goals()
        if g.enabled and g.status.lower() in {"active", "queued", "running"}
    ]


def due_goals(now: float | None = None, limit: int = 5) -> List[GoalSpec]:
    now = time.time() if now is None else float(now)
    goals = list_active_goals()
    scored = []
    for g in goals:
        due = (g.last_tick_at + max(1, int(g.cadence_sec))) <= now
        if due:
            age = max(0.0, now - float(g.last_tick_at or 0.0))
            score = (float(g.priority) * 1000.0) + min(age, 86400.0)
            scored.append((score, g))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [g for _, g in scored[:max(1, int(limit))]]


def mark_goal_tick(goal_id: str, when: float | None = None) -> bool:
    when = time.time() if when is None else float(when)
    goals = load_goals()
    changed = False
    for g in goals:
        if g.goal_id == goal_id:
            g.last_tick_at = when
            g.updated_at = when
            changed = True
            break
    if changed:
        save_goals(goals)
    return changed


def summarize_goals() -> Dict[str, Any]:
    goals = load_goals()
    active = [g for g in goals if g.enabled and g.status == "active"]
    return {
        "ok": True,
        "path": str(goal_store_path()),
        "total": len(goals),
        "active": len(active),
        "titles": [g.title for g in active[:10]],
    }


_TASK_LISTS = {"decision": "decisions", "artifact": "artifacts", "step_done": "steps_done",
               "question": "open_questions", "constraint": "constraints"}
_TASK_CAP = 30
_TASK_IDLE_S = 14 * 86400.0


def open_task(title: str, objective: str = "", constraints: List[str] | None = None) -> GoalSpec:
    """A unit of work that outlives a conversation. A task is a goal the scheduler does not tick."""
    for g in load_goals():
        if "task" in g.tags and g.status == "active" and g.title.strip().lower() == title.strip().lower():
            return g
    return upsert_goal({"title": title, "objective": objective, "constraints": list(constraints or []), "tags": ["task"],
                        "enabled": False, "autonomy_mode": "none", "metadata": {"task": True}})


def current_task(now: float | None = None) -> Optional[GoalSpec]:
    """The task worked on most recently, if it was touched lately enough to still be the one in hand."""
    now = time.time() if now is None else float(now)
    tasks = [g for g in load_goals() if "task" in g.tags and g.status == "active" and now - g.updated_at <= _TASK_IDLE_S]
    return max(tasks, key=lambda g: g.updated_at) if tasks else None


def record_task_event(goal_id: str, kind: str, text: str) -> bool:
    """Add a decision, artifact, finished step, open question or constraint to a task. A question is closed by resolving it."""
    text = " ".join(str(text or "").split())[:300]
    if not text or kind not in _TASK_LISTS and kind != "question_resolved":
        return False
    goals = load_goals()
    for g in goals:
        if g.goal_id != goal_id:
            continue
        meta = g.metadata
        if kind == "question_resolved":
            key = "open_questions"
            meta[key] = [q for q in meta.get(key, []) if q.lower() != text.lower()]
        elif kind == "constraint":
            if text not in g.constraints:
                g.constraints.append(text)
        else:
            lst = meta.setdefault(_TASK_LISTS[kind], [])
            if text not in lst:
                lst.append(text)
            del lst[:-_TASK_CAP]
        g.updated_at = time.time()
        save_goals(goals)
        return True
    return False


def task_brief(limit: int = 2, now: float | None = None) -> str:
    """What is unfinished, for the next session: constraints, decisions, what is done and what is still open."""
    now = time.time() if now is None else float(now)
    tasks = sorted((g for g in load_goals() if "task" in g.tags and g.status == "active" and now - g.updated_at <= _TASK_IDLE_S),
                   key=lambda g: g.updated_at, reverse=True)[:limit]
    lines = []
    for g in tasks:
        m = g.metadata
        bits = [(label, m.get(k) or (g.constraints if k == "constraints" else [])) for label, k in (
            ("constraints", "constraints"), ("decided", "decisions"), ("done", "steps_done"), ("artifacts", "artifacts"), ("open", "open_questions"))]
        detail = "; ".join(f"{label}: {', '.join(v[-3:])}" for label, v in bits if v)
        lines.append(f"  Unfinished task: {g.title}" + (f" — {detail}" if detail else ""))
    return "\n".join(lines)


_CUES = (
    ("constraint", re.compile(r"\b(?:the\s+constraint\s+is|constraint:|must\s+not|must\s+never|has\s+to\s+(?:stay|be|work)|needs\s+to\s+(?:stay|be|work))\b[^.?!]*", re.I)),
    ("decision", re.compile(r"\b(?:we\s+decided(?:\s+to)?|i\s+decided(?:\s+to)?|let'?s\s+go\s+with|the\s+plan\s+is(?:\s+to)?|we(?:'ll|\s+will)\s+use)\b[^.?!]*", re.I)),
    ("step_done", re.compile(r"\b(?:i\s+(?:have\s+)?(?:finished|completed|done)|that(?:'s|\s+is)\s+done|we(?:'ve|\s+have)\s+(?:finished|completed))\b[^.?!]*", re.I)),
    ("question", re.compile(r"\b(?:still\s+need\s+to|we\s+still\s+have\s+to|open\s+question:|next\s+step\s+is|todo:)\b[^.?!]*", re.I)),
)
_START = re.compile(r"\b(?:let'?s\s+(?:work\s+on|start|begin)|i(?:'m|\s+am)\s+(?:working\s+on|building|starting)|the\s+task\s+is|our\s+project\s+is)\s+(?:the\s+|a\s+|an\s+|my\s+)?([^.?!,;]{4,80})", re.I)


def capture_task_events(user_text: str) -> int:
    """Notes what a user message adds to the task in hand, or starts one. Only clear phrasings count."""
    text = str(user_text or "").strip()
    if len(text.split()) < 4 or text.endswith("?"):
        return 0
    task = current_task()
    m = _START.search(text)
    if m and (task is None or m.group(1).strip().lower() not in task.title.lower()):
        task = open_task(m.group(1).strip().rstrip(" ."))
    if task is None:
        return 0
    n = 0
    for kind, pat in _CUES:
        hit = pat.search(text)
        if hit and record_task_event(task.goal_id, kind, hit.group(0)):
            n += 1
    return n
