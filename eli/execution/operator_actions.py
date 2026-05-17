from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


VALID_STATES = {
    "pending",
    "approved",
    "rejected",
    "blocked",
    "pending_confirmation",
    "archived",
}


def _project_root() -> Path:
    try:
        from eli.core.paths import get_paths
        return get_paths().project_root
    except Exception:
        return Path(__file__).resolve().parents[2]


def queue_path(path: Optional[str] = None) -> Path:
    if path:
        return Path(path)
    return _project_root() / "artifacts" / "proactive" / "proposal_queue.jsonl"


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


def _write_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records).rstrip() + "\n"
    path.write_text(text, encoding="utf-8")


def set_proposal_state(
    proposal_id: str,
    new_state: str,
    note: str = "",
    actor: str = "operator_console",
    path: Optional[str] = None,
) -> Dict[str, Any]:
    new_state = str(new_state).strip()
    if new_state not in VALID_STATES:
        return {"ok": False, "error": f"invalid state: {new_state}"}

    qpath = queue_path(path)
    records = _read_jsonl(qpath)
    if not records:
        return {"ok": False, "error": "queue empty", "path": str(qpath)}

    updated = None
    now = time.time()

    for rec in records:
        pid = str(rec.get("proposal_id") or rec.get("id") or "")
        if pid != proposal_id:
            continue

        rec["approval_state"] = new_state
        rec["updated_at"] = now
        rec["approval_actor"] = actor

        meta = rec.get("metadata")
        if not isinstance(meta, dict):
            meta = {}
        hist = meta.get("operator_history")
        if not isinstance(hist, list):
            hist = []
        hist.append({
            "ts": now,
            "actor": actor,
            "state": new_state,
            "note": note or "",
        })
        meta["operator_history"] = hist[-20:]
        rec["metadata"] = meta

        if note:
            rec["operator_note"] = note
            rec["policy_reason"] = note

        updated = rec
        break

    if updated is None:
        return {"ok": False, "error": "proposal not found", "proposal_id": proposal_id, "path": str(qpath)}

    _write_jsonl(qpath, records)
    return {"ok": True, "proposal_id": proposal_id, "state": new_state, "path": str(qpath), "record": updated}
