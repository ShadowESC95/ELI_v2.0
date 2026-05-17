from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def _project_root() -> Path:
    try:
        from eli.core.paths import get_paths
        return get_paths().project_root
    except Exception:
        return Path(__file__).resolve().parents[3]


def _queue_path() -> Path:
    return _project_root() / "artifacts" / "proactive" / "proposal_queue.jsonl"


def _archive_path() -> Path:
    return _project_root() / "artifacts" / "proactive" / "proposal_queue.archive.jsonl"


def _safe_read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out


def _as_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        try:
            val = obj.to_dict()
            if isinstance(val, dict):
                return val
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {"value": str(obj)}


def safe_recent_proposals(limit: int = 25, include_archived: bool = False) -> Dict[str, Any]:
    items = _safe_read_jsonl(_queue_path())
    if include_archived:
        items.extend(_safe_read_jsonl(_archive_path()))
    items = items[-max(1, int(limit)) :]
    items.reverse()
    return {
        "ok": True,
        "count": len(items),
        "items": items,
        "queue_path": str(_queue_path()),
        "archive_path": str(_archive_path()),
    }


def safe_proposal_summary() -> Dict[str, Any]:
    try:
        from eli.planning.proposal_queue import summarize_by_state
        out = summarize_by_state()
        if isinstance(out, dict):
            out.setdefault("ok", True)
            return out
    except Exception:
        pass

    counts: Dict[str, int] = {}
    for rec in _safe_read_jsonl(_queue_path()):
        state = str(rec.get("approval_state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    return {"ok": True, "counts": counts, "path": str(_queue_path())}


def safe_goal_summary() -> Dict[str, Any]:
    try:
        from eli.planning.goal_store import summarize_goals
        out = summarize_goals()
        if isinstance(out, dict):
            out.setdefault("ok", True)
            return out
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "summarize_goals returned non-dict"}


def safe_active_goals(limit: int = 20) -> Dict[str, Any]:
    try:
        from eli.planning.goal_store import list_active_goals
        goals = list_active_goals()
        items = [_as_dict(g) for g in goals[: max(1, int(limit))]]
        return {"ok": True, "count": len(items), "items": items}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "items": []}


def safe_self_model_status() -> Dict[str, Any]:
    root = _project_root()
    from eli.core.paths import persona_auto_path
    persona_auto = persona_auto_path()
    runtime_snapshot = root / "artifacts" / "runtime_snapshot.json"
    goals = root / "artifacts" / "runtime" / "goals.json"
    return {
        "ok": True,
        "persona_auto_exists": persona_auto.exists(),
        "runtime_snapshot_exists": runtime_snapshot.exists(),
        "goal_store_exists": goals.exists(),
        "persona_auto_path": str(persona_auto),
        "runtime_snapshot_path": str(runtime_snapshot),
        "goal_store_path": str(goals),
    }


def operator_snapshot(limit: int = 25) -> Dict[str, Any]:
    return {
        "ok": True,
        "proposal_summary": safe_proposal_summary(),
        "recent_proposals": safe_recent_proposals(limit=limit, include_archived=False),
        "goal_summary": safe_goal_summary(),
        "active_goals": safe_active_goals(limit=limit),
        "self_model": safe_self_model_status(),
    }
