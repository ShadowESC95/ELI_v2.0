from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_SEVERITY_SCORE = {
    "critical": 100,
    "high": 75,
    "medium": 50,
    "low": 25,
    "info": 10,
}

def _project_root() -> Path:
    try:
        from eli.core.paths import get_paths
        return get_paths().project_root
    except Exception:
        return Path(__file__).resolve().parents[3]

def attention_path() -> Path:
    return _project_root() / "artifacts" / "runtime" / "attention_queue.jsonl"

def suppression_path() -> Path:
    return _project_root() / "artifacts" / "runtime" / "attention_suppression.json"

def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
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

def _load_suppression() -> Dict[str, Any]:
    p = suppression_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}

def _save_suppression(data: Dict[str, Any]) -> None:
    p = suppression_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def _severity_score(severity: str) -> int:
    return _SEVERITY_SCORE.get(str(severity or "medium").lower(), 50)

def _rank_item(rec: Dict[str, Any], now: float | None = None) -> float:
    now = time.time() if now is None else float(now)
    sev = _severity_score(str(rec.get("severity") or "medium"))
    ts = float(rec.get("ts") or now)
    freshness = max(0.0, 3600.0 - min(3600.0, now - ts)) / 3600.0
    freshness_score = freshness * 20.0
    state = str(rec.get("state") or "pending")
    state_bonus = 0.0
    if state == "pending_confirmation":
        state_bonus = 20.0
    elif state == "blocked":
        state_bonus = 25.0
    elif state == "pending":
        state_bonus = 10.0
    return float(sev) + freshness_score + state_bonus

def append_attention(
    kind: str,
    title: str,
    state: str = "pending",
    severity: str = "medium",
    source: str = "autonomy_scheduler",
    metadata: Optional[Dict[str, Any]] = None,
    suppression_key: Optional[str] = None,
    suppression_window_sec: int = 0,
) -> Dict[str, Any]:
    now = time.time()
    suppression_key = str(suppression_key or f"{kind}:{title}").strip()
    suppression_window_sec = max(0, int(suppression_window_sec))

    if suppression_window_sec > 0:
        sup = _load_suppression()
        last = float(sup.get(suppression_key, 0.0) or 0.0)
        if last > 0 and (now - last) < suppression_window_sec:
            return {
                "ok": True,
                "suppressed": True,
                "suppression_key": suppression_key,
                "remaining_sec": max(0, int(suppression_window_sec - (now - last))),
            }

    rec = {
        "attention_id": f"attn_{uuid.uuid4().hex[:12]}",
        "ts": now,
        "kind": str(kind or "attention"),
        "title": str(title or "attention").strip(),
        "state": str(state or "pending"),
        "severity": str(severity or "medium"),
        "source": str(source or "autonomy_scheduler"),
        "metadata": dict(metadata or {}),
        "suppression_key": suppression_key,
    }
    rec["rank_score"] = _rank_item(rec, now=now)

    p = attention_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

    if suppression_window_sec > 0:
        sup = _load_suppression()
        sup[suppression_key] = now
        _save_suppression(sup)

    rec["ok"] = True
    rec["suppressed"] = False
    return rec

def recent_attention(limit: int = 25, ranked: bool = True) -> Dict[str, Any]:
    items = _read_jsonl(attention_path())
    if ranked:
        items = sorted(items, key=lambda r: _rank_item(r), reverse=True)
    else:
        items = items[-max(1, int(limit)) :]
        items.reverse()
    items = items[: max(1, int(limit))]
    return {"ok": True, "count": len(items), "items": items, "path": str(attention_path())}

def summarize_attention() -> Dict[str, Any]:
    states: Dict[str, int] = {}
    severities: Dict[str, int] = {}
    for rec in _read_jsonl(attention_path()):
        state = str(rec.get("state") or "unknown")
        sev = str(rec.get("severity") or "unknown")
        states[state] = states.get(state, 0) + 1
        severities[sev] = severities.get(sev, 0) + 1
    return {
        "ok": True,
        "path": str(attention_path()),
        "states": states,
        "severities": severities,
        "needs_attention_now": states.get("blocked", 0) + states.get("pending_confirmation", 0),
    }

def top_attention(limit: int = 10) -> Dict[str, Any]:
    return recent_attention(limit=limit, ranked=True)
