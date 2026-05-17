from __future__ import annotations

import re
from typing import List

_LATEXISH = re.compile(
    r'(\$[^$]+\$|\\\[[\s\S]*?\\\]|\\\([^\)]*\\\)|[A-Za-z0-9_]+(?:\s*=\s*|\s*\\approx\s*|\s*\\sim\s*)[^\n,;]+)'
)

def extract_equations_from_text(text: str) -> List[str]:
    if not text:
        return []
    out = []
    seen = set()
    for m in _LATEXISH.finditer(text):
        s = m.group(0).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out

def extract_equations(text: str) -> List[str]:
    return extract_equations_from_text(text)

__all__ = ["extract_equations_from_text", "extract_equations"]
