"""Durable per-step record for MULTI_COMMAND so a crash mid-sequence leaves a real trace,
and a resubmit of the same phrase doesn't re-run steps that already succeeded."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

_RESUME_WINDOW_S = 3600.0      # a repeat past this is a new request, not a resume
_MAX_AGE_S = 7 * 86400.0       # prune records older than this
_MAX_RECORDS = 200


def _log_path() -> Path:
    override = os.environ.get("ELI_COMMAND_SEQUENCE_LOG", "").strip()
    if override:
        return Path(override).expanduser()
    from eli.core.paths import artifacts_dir
    return artifacts_dir() / "runtime" / "command_sequences.json"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _load() -> List[Dict[str, Any]]:
    path = _log_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def _prune(records: List[Dict[str, Any]], now: float) -> List[Dict[str, Any]]:
    kept = [r for r in records if now - float(r.get("updated_at") or 0.0) <= _MAX_AGE_S]
    kept.sort(key=lambda r: float(r.get("updated_at") or 0.0), reverse=True)
    return kept[:_MAX_RECORDS]


def _save(records: List[Dict[str, Any]]) -> None:
    _atomic_write(_log_path(), json.dumps(records, indent=2))


def start_or_resume(raw: str, commands: List[str], now: Optional[float] = None) -> Dict[str, Any]:
    """Look up an incomplete record with the same normalized raw text, within the resume
    window. Returns {sequence_id, resumed, done_ok} — done_ok maps index -> already-rendered
    part text for steps that succeeded last time and must not be re-run."""
    now = time.time() if now is None else float(now)
    key = _normalize(raw)
    records = _prune(_load(), now)

    for r in records:
        if (r.get("raw_key") == key and not r.get("completed")
                and now - float(r.get("updated_at") or 0.0) <= _RESUME_WINDOW_S):
            done_ok = {int(i): s["text"] for i, s in (r.get("steps") or {}).items() if s.get("ok")}
            _save(records)
            return {"sequence_id": r["sequence_id"], "resumed": bool(done_ok), "done_ok": done_ok}

    sequence_id = f"cmdseq_{uuid.uuid4().hex[:12]}"
    records.insert(0, {
        "sequence_id": sequence_id, "raw_key": key, "raw": str(raw or ""),
        "commands": list(commands or []), "steps": {}, "started_at": now,
        "updated_at": now, "completed": False,
    })
    _save(records)
    return {"sequence_id": sequence_id, "resumed": False, "done_ok": {}}


def mark_step(sequence_id: str, index: int, ok: bool, text: str, now: Optional[float] = None) -> None:
    now = time.time() if now is None else float(now)
    records = _load()
    for r in records:
        if r.get("sequence_id") == sequence_id:
            r.setdefault("steps", {})[str(index)] = {"ok": bool(ok), "text": str(text or "")}
            r["updated_at"] = now
            break
    _save(_prune(records, now))


def finish(sequence_id: str, all_ok: bool, now: Optional[float] = None) -> None:
    now = time.time() if now is None else float(now)
    records = _load()
    for r in records:
        if r.get("sequence_id") == sequence_id:
            r["completed"] = bool(all_ok)
            r["updated_at"] = now
            break
    _save(_prune(records, now))
