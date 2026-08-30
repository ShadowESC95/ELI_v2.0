"""Rule-based code patches for recurring executor failures without LLM guessing.

Some failures are parameter-shape or alias bugs with a known, minimal fix.
``run_patch_cycle`` tries these before asking the model to invent a file path.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def _project_root() -> Path:
    from eli.core.paths import source_root
    return source_root()


def _safe_str(v: Any) -> str:
    return str(v or "").strip()


def propose_deterministic_patch(failure: dict) -> Optional[Dict[str, Any]]:
    """Return a patch dict compatible with ``SelfImprovement.apply_code_patch``."""
    err = _safe_str(failure.get("error", ""))
    cmd = _safe_str(failure.get("command", "")).upper()
    err_low = err.lower()

    patches: List[Dict[str, str]] = []

    if "missing topic for document generation" in err_low or cmd.startswith("CREATE_DOCUMENT"):
        doc_path = _project_root() / "eli/execution/executor_enhanced.py"
        if doc_path.is_file():
            doc_src = doc_path.read_text(encoding="utf-8")
            if 'args.get("name")' in doc_src and 'args.get("target")' in doc_src:
                return {
                    "ok": True,
                    "already_applied": True,
                    "file": "eli/execution/executor_enhanced.py",
                    "description": "CREATE_DOCUMENT accepts name/target/title/query topic aliases",
                    "deterministic": True,
                }
        patches.append(
            {
                "file": "eli/execution/executor_enhanced.py",
                "old": (
                    'topic = (args.get("topic") or args.get("text") or '
                    'args.get("description") or args.get("prompt") or "").strip()'
                ),
                "new": (
                    'topic = (args.get("topic") or args.get("text") or '
                    'args.get("description") or args.get("prompt") or '
                    'args.get("name") or args.get("target") or args.get("title") or '
                    'args.get("query") or "").strip()'
                ),
                "description": (
                    "Accept name/target/title/query as CREATE_DOCUMENT topic aliases"
                ),
            }
        )

    if "unsupported executor action: create_doc" in err_low or cmd.startswith("CREATE_DOC"):
        alias_path = _project_root() / "eli/execution/executor_enhanced.py"
        if alias_path.is_file():
            alias_src = alias_path.read_text(encoding="utf-8")
            if '"CREATE_DOC": "CREATE_DOCUMENT"' in alias_src:
                return {
                    "ok": True,
                    "already_applied": True,
                    "file": "eli/execution/executor_enhanced.py",
                    "description": "CREATE_DOC aliased to CREATE_DOCUMENT",
                    "deterministic": True,
                }
        patches.append(
            {
                "file": "eli/execution/executor_enhanced.py",
                "old": '        "LS": "LIST_DIR",',
                "new": (
                    '        "LS": "LIST_DIR",\n'
                    '        "CREATE_DOC": "CREATE_DOCUMENT",\n'
                    '        "WRITE_DOCUMENT": "CREATE_DOCUMENT",'
                ),
                "description": "Alias CREATE_DOC/WRITE_DOCUMENT to CREATE_DOCUMENT",
            }
        )

    for spec in patches:
        path = _project_root() / spec["file"]
        if not path.is_file():
            continue
        src = path.read_text(encoding="utf-8")
        if spec["new"] in src:
            return {
                "ok": True,
                "already_applied": True,
                "file": spec["file"],
                "description": spec["description"],
                "deterministic": True,
            }
        if spec["old"] not in src:
            continue
        return {
            "ok": True,
            "file": spec["file"],
            "old": spec["old"],
            "new": spec["new"],
            "description": spec["description"],
            "deterministic": True,
        }
    return None
