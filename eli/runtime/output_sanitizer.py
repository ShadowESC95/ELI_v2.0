from __future__ import annotations

import inspect
import re
from typing import Any


_PRIVATE_BLOCKS = [
    re.compile(r"(?is)\[PRIVATE REASONING STRATEGY.*?\[/END\]"),
    re.compile(r"(?is)\[PRIVATE REASONING STRATEGATEGY.*?\[/END\]"),
]

_BAD_VISIBLE_PREFIXES = (
    "<generator object",
    "{'ok':",
    '{"ok":',
)


def _consume_generator(value: Any) -> str:
    chunks: list[str] = []
    for part in value:
        if part is None:
            continue
        chunks.append(str(part))
    return "".join(chunks).strip()


def stringify_output(value: Any) -> str:
    if inspect.isgenerator(value):
        return _consume_generator(value)

    if isinstance(value, dict):
        for key in ("response", "content", "message", "text"):
            val = value.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    if value is None:
        return ""

    return str(value).strip()


def sanitize_visible_output(value: Any) -> str:
    text = stringify_output(value)

    for pat in _PRIVATE_BLOCKS:
        text = pat.sub("", text).strip()

    low = text.lstrip().lower()
    if any(low.startswith(p.lower()) for p in _BAD_VISIBLE_PREFIXES):
        return ""

    return text
