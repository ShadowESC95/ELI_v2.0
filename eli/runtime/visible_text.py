from __future__ import annotations

from typing import Any


def _consume_generator(gen: Any) -> str:
    parts: list[str] = []
    for chunk in gen:
        if chunk is None:
            continue

        if isinstance(chunk, str):
            parts.append(chunk)
            continue

        if isinstance(chunk, dict):
            for key in ("response", "content", "message", "text", "delta", "result", "answer", "output"):
                value = chunk.get(key)
                if value is not None and str(value).strip():
                    parts.append(str(value))
                    break
            continue

        parts.append(str(chunk))

    return "".join(parts).strip()


def to_user_visible_text(result: Any) -> str:
    """
    Convert CognitiveEngine/process outputs into GUI-safe visible text.

    Boundary contract:
    - strings remain strings
    - dicts expose response/content/etc.
    - generators are consumed into text
    - raw dict envelopes are not dumped into chat widgets
    """
    if result is None:
        return ""

    if hasattr(result, "__next__"):
        return _consume_generator(result)

    if isinstance(result, str):
        return result.strip()

    if isinstance(result, dict):
        for key in ("response", "content", "message", "text", "result", "answer", "output"):
            value = result.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()

        action = str(result.get("action") or "UNKNOWN").strip() or "UNKNOWN"
        return f"No user-visible response was produced for action {action}."

    return str(result).strip()
