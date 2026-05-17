from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import json
import time

from eli.core.paths import get_paths


def trace_path() -> Path:
    p = Path(get_paths().artifacts_dir) / "runtime" / "last_trace.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def save_last_trace(payload: Dict[str, Any]) -> Path:
    data = dict(payload or {})
    data["saved_at"] = time.time()
    p = trace_path()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def load_last_trace() -> Dict[str, Any]:
    p = trace_path()
    if not p.exists():
        return {}
    try:
        return dict(json.loads(p.read_text(encoding="utf-8")) or {})
    except Exception:
        return {}


# Trace payloads may include meta.response_mode from executor/router surfaces.
