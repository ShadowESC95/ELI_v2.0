from __future__ import annotations

from typing import Any, Dict

COGNITIVE_DEFAULT = "cognitive_response"
GROUNDED_REPORT = "grounded_report"
PLAN_AND_EXECUTE = "plan_and_execute"
RAW_MEMORY_DUMP = "raw_memory_dump"

GROUNDED_ACTIONS = {
    "RUNTIME_AUDIT",
    "RESOLVE_RUNTIME_PATHS",
    "IMPORT_SURFACE_AUDIT",
    "LAST_TRACE_REPORT",
    "REASONING_MODE_REPORT",
    "MEMORY_STATUS",
    "FIRST_INTERACTION_REPORT",
    "IDENTITY_MEMORY_REPORT",
    "USER_MEMORY_DUMP",
    "COGNITION_STATUS",
    "GUI_RUNTIME_AUDIT",
    "FRONTIER_STATUS",
    "ELI_IDENTITY_AUDIT",
}

EXECUTION_ACTION_HINTS = {
    "OPEN_APP",
    "OPEN_URL",
    "RUN_COMMAND",
    "SHELL",
    "FILE_WRITE",
    "FILE_READ",
    "SEARCH_WEB",
    "WEB_SEARCH",
}


def classify_response_mode(action: str, args: Dict[str, Any] | None = None, meta: Dict[str, Any] | None = None) -> str:
    action = str(action or "").strip().upper()
    args = dict(args or {})
    meta = dict(meta or {})
    if action in GROUNDED_ACTIONS:
        return GROUNDED_REPORT
    if action in EXECUTION_ACTION_HINTS:
        return PLAN_AND_EXECUTE
    if action == "MEMORY_RECALL":
        msg = str(args.get("query") or args.get("message") or "").lower()
        if any(p in msg for p in (
            "give me everything", "don't summarise", "do not summarise", "raw memory", "full dump", "verbatim",
        )):
            return RAW_MEMORY_DUMP
    return COGNITIVE_DEFAULT


def should_force_cognitive_for_user_text(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False
    cognitive_patterns = (
        "who am i",
        "who are you",
        "what do you remember of me",
        "what do you know about me",
        "what do you know about yourself",
        "what habits",
        "explain your memory system",
        "explain exactly how your memory system works",
        "explain your cognition pipeline",
        "how does your memory system work",
        "how does your cognition pipeline work",
        "if i ask you something you're wrong about",
        "what is with the calmly",
    )
    if any(p in low for p in cognitive_patterns):
        if any(x in low for x in (
            "timestamp included",
            "resolved runtime paths",
            "what imports are failing",
            "run a full runtime audit",
            "raw memory dump",
            "don't summarise",
            "do not summarise",
            "every table",
            "row count",
        )):
            return False
        return True
    return False
