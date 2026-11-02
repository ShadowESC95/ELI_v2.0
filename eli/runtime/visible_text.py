from __future__ import annotations

from typing import Any


def _consume_generator(gen: Any) -> str:
    from eli.kernel.engine import MAIN_REPLY_DONE_SENTINEL as _done
    parts: list[str] = []
    try:
        for chunk in gen:
            if chunk is None or chunk == _done:
                continue
            if isinstance(chunk, str):
                parts.append(chunk)
            elif isinstance(chunk, dict):
                val = (
                    chunk.get("response")
                    or chunk.get("content")
                    or chunk.get("text")
                    or chunk.get("delta")
                    or chunk.get("message")
                    or chunk.get("result")
                    or chunk.get("answer")
                )
                if val:
                    parts.append(str(val))
            else:
                parts.append(str(chunk))
    except Exception as e:
        parts.append(f"[stream failed: {type(e).__name__}: {e}]")
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
            if value is None:
                continue
            # A streamed field can itself be an UNCONSUMED generator (e.g. process(stream=True)
            # returning {"response": <gen>} on the keyword-fallback path). str() on it would dump
            # "<generator object ...>" into the chat — consume it into text instead.
            if hasattr(value, "__next__"):
                text = _consume_generator(value)
            else:
                text = str(value).strip()
            if text:
                return text

        action = str(result.get("action") or "UNKNOWN").strip() or "UNKNOWN"
        return f"No user-visible response was produced for action {action}."

    return str(result).strip()
