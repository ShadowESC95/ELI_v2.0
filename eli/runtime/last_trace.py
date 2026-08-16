from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import json
import os
import time

from eli.core.paths import get_paths

# One process = one session. The trace file persists across restarts, so without
# this a question about "your last response" was answered from whatever run last
# wrote the file — observed live at 2.1.96: a turn saved at 15:46 was reported as
# the last response at 17:32, 106 minutes and one restart later, from a session
# the user had already closed.
#
# The PID is the check rather than a stored session id because it is what
# actually distinguishes runs, and it cannot be forgotten to update.
_SESSION_PID = os.getpid()


def trace_path() -> Path:
    p = Path(get_paths().artifacts_dir) / "runtime" / "last_trace.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def save_last_trace(payload: Dict[str, Any]) -> Path:
    data = dict(payload or {})
    data["saved_at"] = time.time()
    data["session_pid"] = _SESSION_PID
    p = trace_path()
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def load_last_trace(*, any_session: bool = False) -> Dict[str, Any]:
    """The last response trace THIS run recorded, or {} if there isn't one.

    A trace from an earlier run is treated as absent, not as an answer. Reporting
    it was worse than saying nothing: request ids restart at req-000001 every
    session, so a stale payload is indistinguishable from a live one by id, and
    it was served with full confidence as "your last response".

    `any_session=True` returns it regardless — for diagnostics that genuinely
    want the last trace on disk rather than the last one in this conversation.
    """
    p = trace_path()
    if not p.exists():
        return {}
    try:
        data = dict(json.loads(p.read_text(encoding="utf-8")) or {})
    except Exception:
        return {}
    if any_session:
        return data
    if data.get("session_pid") != _SESSION_PID:
        return {}
    return data


# Trace payloads may include meta.response_mode from executor/router surfaces.
