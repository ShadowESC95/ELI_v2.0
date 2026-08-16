from __future__ import annotations

import json
from pathlib import Path
from typing import List

from eli.runtime.tool_result_models import ToolResultRecord


def _project_root() -> Path:
    # Canonical env-honoring root — __file__ resolves into the read-only
    # bundle in frozen builds.
    try:
        from eli.core.paths import project_root
        return Path(project_root())
    except Exception:
        return Path(__file__).resolve().parents[3]


def tool_result_store_path() -> Path:
    # This WRITES, so resolving it under the project root is worse than a stale
    # read: in a packaged build that root is a read-only AppImage mount and the
    # mkdir below fails outright. Data belongs in the artifacts dir, which is
    # user-writable by construction.
    try:
        from eli.core.paths import data_dir as _dd
        base = Path(_dd())
    except Exception:
        base = _project_root() / "artifacts"
    p = base / "runtime" / "tool_results.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def append_tool_result(rec: ToolResultRecord) -> Path:
    p = tool_result_store_path()
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
    return p


def load_recent_tool_results(limit: int = 25) -> List[ToolResultRecord]:
    p = tool_result_store_path()
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    out: List[ToolResultRecord] = []
    for line in lines[-max(1, int(limit)):]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(ToolResultRecord.from_any(json.loads(line)))
        except Exception:
            continue
    return out
