"""
eli/core/grounding.py
─────────────────────
Single source of truth for grounded-query detection.

Previously each of agent_bus, engine, and router_enhanced maintained their own
trigger lists/regexes for "does this query require grounded evidence from source
files, memory, or the runtime?" — all three could disagree on the same input.

This module provides one canonical function. Import it everywhere; don't
duplicate the logic.

    from eli.core.grounding import is_grounded_query
"""
from __future__ import annotations
import re
from typing import Optional


# Actions that are always grounded regardless of the input text.
_GROUNDED_ACTIONS: frozenset = frozenset({
    "RUNTIME_AUDIT",
    "IMPORT_AUDIT",
    "RESOLVE_RUNTIME_PATHS",
    "GUI_RUNTIME_AUDIT",
    "EXPLAIN_MEMORY_RUNTIME",
    "EXPLAIN_COGNITION_RUNTIME",
    "RUNTIME_STATUS",
    "MEMORY_STATUS",
    "COGNITION_STATUS",
    "LIST_CAPABILITIES",
    "AWARENESS_STATUS",
    "CODE_CHANGES",
    "FRONTIER_STATUS",
    "ELI_IDENTITY_AUDIT",
    "SELF_ANALYZE",
    "SELF_IMPROVE",
    "SELF_PATCH",
    "EXPLAIN_ALL_REASONING_MODES",
})

# Substring triggers — any of these present in lowercased user_input → grounded.
# Merged superset of: agent_bus._query_is_grounded triggers +
#                     engine._is_grounded_status_query triggers +
#                     router _RE_GROUNDED_PIPELINE patterns.
_TRIGGERS: tuple = (
    # Identity / user knowledge
    "who am i",
    "who are you",
    "who created you",
    "how were you created",
    "what do you know about me",
    "what do you remember",
    "do you remember me",
    "what is my name",
    "remember me",
    # Memory internals
    "how does your memory work",
    "how does memory work",
    "memory recall",
    "memory storage",
    "memory internals",
    "memory system",
    "how many memories",
    "what memories do you have",
    "from memory",
    # Conversation history
    "what were we discussing",
    "last conversation",
    "yesterday",
    "3 days ago",
    "three days ago",
    # Runtime / architecture
    "what are you running",
    "what files are involved",
    "gpu layers",
    "context size",
    "batch",
    "temperature",
    "what are your capabilities",
    "what can you do",
    "list capabilities",
    "runtime audit",
    "import audit",
    "what changed",
    "wiring",
    "line ",
    ".py",
    "db table",
    "db tables",
    "which file",
    "which files",
    # Pipeline / cognition
    "broker",
    "orchestrator",
    "agent bus",
    "prompt to response",
    "prompt->response",
    "response loop",
    "pipeline",
    "pipeline stages",
    "cognition pipeline",
    "cognitive pipeline",
    "how many stages",
    "how do you work",
    "how does your cognition",
    "input to output",
    "every step",
    # Agents / capabilities
    "how many agents",
    "agent roster",
    "what agents",
    "which agents",
    "folders and paths involved",
    "full wiring",
    # Specific audit types
    "full system audit",
    "full system wiring",
    "cross-system matrix",
    "eli identity audit",
    "classify eli",
    "classification audit",
    "frontier status",
    # System components mentioned by name
    "world tab",
    "labs tab",
    "image engine",
    "proactive daemon",
    # Diagnostics / health
    "diagnostic",
    "diagnostics",
    "full audit",
)


def is_grounded_query(user_input: str, action: Optional[str] = None) -> bool:
    """Return True if this query requires reading source evidence (files, memory,
    runtime state) rather than relying on the model's priors alone.

    Args:
        user_input: raw user text (any case).
        action:     router action string, e.g. "RUNTIME_AUDIT". Optional.
    """
    if action and action.upper() in _GROUNDED_ACTIONS:
        return True
    low = (user_input or "").strip().lower()
    return any(t in low for t in _TRIGGERS)
