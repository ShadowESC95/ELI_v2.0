"""Small tolerant JSON readers shared across the runtime."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from eli.utils.log import get_logger

log = get_logger(__name__)


def read_json_dict(path: Path) -> Dict[str, Any]:
    """The JSON object in ``path``, or {} if it is missing, unreadable or not an object."""
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        log.debug("could not read %s", path, exc_info=True)
    return {}


def read_jsonl_dicts(path: Path) -> List[Dict[str, Any]]:
    """Every JSON object line in ``path``; blank and malformed lines are skipped."""
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
