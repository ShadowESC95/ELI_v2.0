from __future__ import annotations

import json
from pathlib import Path
from typing import List

from eli.runtime.tool_result_models import ToolResultRecord


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def tool_result_store_path() -> Path:
    p = _project_root() / "artifacts" / "runtime" / "tool_results.jsonl"
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
