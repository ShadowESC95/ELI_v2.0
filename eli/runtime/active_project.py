"""Active project signal.

A tiny, file-backed pointer to the project the user is currently working in
(set from the Labs Projects tab). When set:
  • new scheduled/overnight tasks are owned by it (meta["project"]) — Phase 3
  • new durable memories are tagged with its memory_tag — Phase 2

Default = no active project → zero behaviour change. Persisted to
artifacts/runtime/active_project.json so it survives a restart.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, Optional

_LOCK = threading.RLock()


def _path() -> Path:
    try:
        from eli.core.paths import get_paths
        base = get_paths().artifacts_dir / "runtime"
    except Exception:
        base = Path(__file__).resolve().parents[2] / "artifacts" / "runtime"
    base.mkdir(parents=True, exist_ok=True)
    return base / "active_project.json"


def set_active(name: str, memory_tag: str = "") -> None:
    name = (name or "").strip()
    if not name:
        clear_active()
        return
    tag = (memory_tag or f"project.{name.lower().replace(' ', '_')}").strip()
    with _LOCK:
        try:
            _path().write_text(json.dumps({"name": name, "memory_tag": tag,
                                           "ts": time.time()}, indent=2), encoding="utf-8")
        except Exception:
            pass


def get_active() -> Optional[Dict[str, str]]:
    with _LOCK:
        p = _path()
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict) and d.get("name"):
                return {"name": str(d["name"]), "memory_tag": str(d.get("memory_tag") or "")}
        except Exception:
            return None
    return None


def active_name() -> str:
    a = get_active()
    return a["name"] if a else ""


def active_memory_tag() -> str:
    a = get_active()
    return a["memory_tag"] if a else ""


def clear_active() -> None:
    with _LOCK:
        try:
            _path().unlink(missing_ok=True)
        except Exception:
            pass


__all__ = ["set_active", "get_active", "active_name", "active_memory_tag", "clear_active"]
