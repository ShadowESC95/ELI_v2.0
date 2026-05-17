from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_MODE_LABELS = {
    "quick": "Quick",
    "chain_of_thought": "Chain of Thought",
    "cot": "Chain of Thought",
    "self_consistency": "Self-Consistency",
    "tree_of_thoughts": "Tree of Thoughts",
    "tot": "Tree of Thoughts",
    "constitutional_ai": "Constitutional AI",
    "const_ai": "Constitutional AI",
}

_ATTRS = (
    "reasoning_mode",
    "active_reasoning_mode",
    "current_reasoning_mode",
    "selected_reasoning_mode",
    "_reasoning_mode",
    "_active_reasoning_mode",
    "_current_reasoning_mode",
    "_selected_reasoning_mode",
    "_last_reasoning_mode",
    "_trace_reasoning_mode",
)

_SETTING_KEYS = (
    "reasoning_mode",
    "active_reasoning_mode",
    "current_reasoning_mode",
    "default_reasoning_mode",
)

def _norm(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = raw.replace("⚡", "").replace("🔗", "").replace("🔄", "").replace("🌳", "").replace("⚖️", "").strip()
    low = raw.lower().replace("-", "_").replace(" ", "_")

    if "tree" in low or low in {"tot"}:
        return "tree_of_thoughts"
    if "constitutional" in low or "const" in low:
        return "constitutional_ai"
    if "self" in low and "consistency" in low:
        return "self_consistency"
    if "chain" in low or low in {"cot", "co_t"}:
        return "chain_of_thought"
    if "quick" in low or "fast" in low:
        return "quick"

    return low

def _label(key: str) -> str:
    key = _norm(key) or "quick"
    try:
        from eli.cognition.reasoning_modes import mode_display
        val = mode_display(key)
        if val:
            return str(val)
    except Exception:
        pass
    return _MODE_LABELS.get(key, key.replace("_", " ").title())

def _project_root() -> Path:
    return Path(os.environ.get("ELI_PROJECT_ROOT", Path.cwd())).resolve()

def _read_json(path: Path) -> dict:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}

def _from_trace_files() -> str:
    root = _project_root()
    candidates = [
        root / "artifacts" / "runtime" / "last_trace.json",
        root / "artifacts" / "runtime" / "state.json",
        root / "artifacts" / "runtime_snapshot.json",
    ]
    for path in candidates:
        data = _read_json(path)
        stack = [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, dict):
                for k, v in obj.items():
                    lk = str(k).lower()
                    if ("reasoning" in lk and "mode" in lk) or lk in {"mode", "reasoning_mode"}:
                        n = _norm(v)
                        if n:
                            return n
                    if isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(obj, list):
                stack.extend(obj)
    return ""

def _from_settings() -> str:
    root = _project_root()
    for path in [root / "config" / "settings.json", Path.cwd() / "config" / "settings.json"]:
        data = _read_json(path)
        for key in _SETTING_KEYS:
            n = _norm(data.get(key))
            if n:
                return n
        modes = data.get("reasoning_modes")
        if isinstance(modes, dict):
            n = _norm(modes.get("active") or modes.get("default"))
            if n:
                return n
    return ""

def _from_engine(engine: Any) -> str:
    if engine is None:
        return ""

    for attr in _ATTRS:
        try:
            n = _norm(getattr(engine, attr, None))
        except Exception:
            n = ""
        if n:
            return n

    try:
        d = vars(engine)
    except Exception:
        d = {}

    for k, v in d.items():
        lk = str(k).lower()
        if "reason" in lk and "mode" in lk:
            n = _norm(v)
            if n:
                return n

    return ""

def current_reasoning_mode(engine: Any = None, override: Any = None) -> str:
    n = _norm(override)
    if n:
        return n

    n = _from_engine(engine)
    if n:
        return n

    for env_key in ("ELI_REASONING_MODE", "ELI_ACTIVE_REASONING_MODE", "ELI_CURRENT_REASONING_MODE"):
        n = _norm(os.environ.get(env_key))
        if n:
            return n

    n = _from_trace_files()
    if n:
        return n

    n = _from_settings()
    if n:
        return n

    return "quick"

def current_reasoning_mode_label(engine: Any = None, override: Any = None) -> str:
    return _label(current_reasoning_mode(engine, override=override))

def current_reasoning_mode_text(engine: Any = None, override: Any = None, explain: bool = True) -> str:
    # ELI_REASONING_MODE_TEXT_DESCRIPTION_V1
    # Pulls per-mode description from cognition/reasoning_modes.mode_description()
    # so the four private modes get distinct, code-grounded explanations instead
    # of one shared boilerplate paragraph.
    key = current_reasoning_mode(engine, override=override)
    label = _label(key)
    if not explain:
        return f"Current reasoning mode: {label}"
    try:
        from eli.cognition.reasoning_modes import mode_description
        desc = mode_description(key)
    except Exception:
        desc = ""
    if desc:
        return f"Current reasoning mode: {label}\n\n{desc}"
    return f"Current reasoning mode: {label}"

__all__ = [
    "current_reasoning_mode",
    "current_reasoning_mode_label",
    "current_reasoning_mode_text",
]
