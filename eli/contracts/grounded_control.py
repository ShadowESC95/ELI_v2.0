"""
Grounded-control synthesis guard for ELI.

Purpose:
- Prevent final-loop clarification fallback when a routed grounded/control action
  already has complete executor evidence.
- Preserve normal non-Quick synthesis: this guard does not bypass the first
  synthesis attempt.
- It only blocks the later "ask the user to clarify" fallback when evidence is
  already complete.
"""

from __future__ import annotations

from typing import Any, Mapping
import re


GROUNDED_CONTROL_ACTIONS = {
    "RUNTIME_STATUS",
    "MEMORY_COUNT",
    "MEMORY_STATUS",
    "MEMORY_RECALL",
    "GUI_RUNTIME_AUDIT",
    "EXPLAIN_MEMORY_RUNTIME",
    "EXPLAIN_LAST_RESPONSE",
    "SELF_REPORT",
}


RUNTIME_STATUS_REQUIRED_TERMS = (
    "provider",
    "model_name",
    "model_path",
    "context_size",
    "gpu_layers",
    "batch_size",
    "cpu_threads",
    "max_tokens",
    "temperature",
    "use_mmap",
    "use_mlock",
)


BAD_CLARIFY_PATTERNS = (
    "what specific details",
    "what specific aspects",
    "could you please clarify",
    "please clarify",
    "what do you need to know specifically",
    "model, context size, gpu layers",
)


def _safe_str(value: Any, *, limit: int = 6000) -> str:
    try:
        if value is None:
            return ""
        if isinstance(value, str):
            return value[:limit]
        return repr(value)[:limit]
    except Exception:
        return ""


def _collect_text(value: Any, *, limit: int = 50000, depth: int = 0) -> str:
    if value is None or depth > 5 or limit <= 0:
        return ""

    if isinstance(value, str):
        return value[:limit]

    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, val in value.items():
            if len("\n".join(parts)) >= limit:
                break
            k = _safe_str(key, limit=200)
            if k:
                parts.append(k)
            parts.append(_collect_text(val, limit=max(1000, limit // 4), depth=depth + 1))
        return "\n".join(p for p in parts if p)[:limit]

    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            if len("\n".join(parts)) >= limit:
                break
            parts.append(_collect_text(item, limit=max(1000, limit // 4), depth=depth + 1))
        return "\n".join(p for p in parts if p)[:limit]

    return _safe_str(value, limit=limit)


def _lookup_action(local_vars: Mapping[str, Any]) -> str:
    direct_names = (
        "action",
        "final_action",
        "route_action",
        "control_action",
        "intent_action",
        "routed_action",
    )

    for name in direct_names:
        value = local_vars.get(name)
        if value:
            return str(value).strip().upper()

    container_names = (
        "route",
        "router_result",
        "parsed",
        "intent",
        "agent_result",
        "bus_result",
        "result",
        "executor_result",
        "control",
    )

    for name in container_names:
        value = local_vars.get(name)
        if isinstance(value, Mapping):
            for key in ("action", "final_action", "routed_action"):
                if value.get(key):
                    return str(value.get(key)).strip().upper()

    blob = _collect_text(local_vars, limit=20000).upper()
    for action in GROUNDED_CONTROL_ACTIONS:
        if action in blob:
            return action

    return ""


def _looks_like_runtime_status_complete(text: str) -> bool:
    low = text.lower()

    # Accept either structured contract terms or executor/report terms.
    hits = sum(1 for term in RUNTIME_STATUS_REQUIRED_TERMS if term.lower() in low)

    has_model = "qwen" in low or ".gguf" in low or "model_name" in low or "model path" in low
    has_ctx = "context_size" in low or "context size" in low or "n_ctx" in low
    has_gpu = "gpu_layers" in low or "gpu layers" in low or "n_gpu_layers" in low
    has_batch = "batch_size" in low or "batch size" in low or "n_batch" in low
    has_threads = "cpu_threads" in low or "cpu threads" in low or "n_threads" in low

    return hits >= 7 or (has_model and has_ctx and has_gpu and has_batch and has_threads)


def _looks_like_memory_count_complete(text: str) -> bool:
    low = text.lower()
    return (
        ("memory" in low or "memories" in low)
        and any(x in low for x in ("count", "total", "rows", "records"))
        and any(ch.isdigit() for ch in low)
    )


def evidence_complete_for_action(action: str, local_vars: Mapping[str, Any]) -> bool:
    action = str(action or "").strip().upper()
    if action not in GROUNDED_CONTROL_ACTIONS:
        return False

    text = _collect_text(local_vars, limit=70000)

    if action == "RUNTIME_STATUS":
        return _looks_like_runtime_status_complete(text)

    if action in {"MEMORY_COUNT", "MEMORY_STATUS"}:
        return _looks_like_memory_count_complete(text)

    # Conservative generic rule for other grounded controls:
    # only suppress clarification when the executor returned ok evidence/content.
    low = text.lower()
    return (
        "ok" in low
        and any(x in low for x in ("content", "response", "report", "evidence"))
        and not any(x in low for x in ("traceback", "exception", "error:"))
    )


def should_suppress_clarification(local_vars: Mapping[str, Any]) -> bool:
    """
    Called from the final synthesis confidence branch.

    Return True only when:
    - the routed action is grounded/control;
    - evidence is already complete;
    - therefore asking the user to clarify would be wrong.
    """
    if not isinstance(local_vars, Mapping):
        return False

    action = _lookup_action(local_vars)
    if action not in GROUNDED_CONTROL_ACTIONS:
        return False

    return evidence_complete_for_action(action, local_vars)


def looks_like_bad_clarification(text: str) -> bool:
    low = str(text or "").lower().strip()
    if not low:
        return False
    if not low.endswith("?"):
        return False
    return any(pattern in low for pattern in BAD_CLARIFY_PATTERNS)
