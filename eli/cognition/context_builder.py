"""
eli.cognition.context_builder

Builds system prompt context for ELI:
- Persona: eli/cognition/persona.txt
- Recent memory: SQLite via eli.memory.recall_recent()
- Capabilities: optional best-effort

This file must NEVER crash the chat pipeline.
"""

from __future__ import annotations
from pathlib import Path
from typing import List
import os

from eli.memory import recall_recent


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def _project_root() -> Path:
    return Path(os.environ.get("ELI_ROOT", Path(__file__).resolve().parents[2])).resolve()


def _persona_block(root: Path) -> str:
    persona_path = root / "eli" / "cognition" / "persona.txt"
    persona = _read_text(persona_path)
    if not persona:
        persona = "You are ELI (Entropy Logical Interface). Be correct, useful, and honest."
    return "=== ELI PERSONA (source: eli/cognition/persona.txt) ===\n" + persona.strip()


def _memory_block(limit: int = 30) -> str:
    try:
        items = recall_recent(k=limit)
    except Exception:
        items = []

    if not items:
        return "=== RECENT MEMORY (SQLite) ===\n(no recent memories returned)"

    lines: List[str] = []
    for m in items:
        src = (m.get("source") or m.get("tags") or "").strip()
        txt = (m.get("content") or m.get("text") or "").strip()
        if not txt:
            continue
        if src:
            lines.append(f"- ({src}) {txt}")
        else:
            lines.append(f"- {txt}")

    if not lines:
        return "=== RECENT MEMORY (SQLite) ===\n(no recent memories returned)"

    return "=== RECENT MEMORY (SQLite) ===\n" + "\n".join(lines[:limit])


def build_context(user_message: str = '', user_text: str | None = None, query: str | None = None) -> str:
    # Compat arg normalization
    if not user_message:
        user_message = user_text or query or ''

    # Persona block (best effort)
    persona = ''
    try:
        from pathlib import Path as _Path
        _here = _Path(__file__).resolve().parent
        persona_path = _here / 'persona.txt' if (_here / 'persona.txt').exists() else _here.parent / 'persona' / 'persona.txt'
        if persona_path.exists():
            persona = persona_path.read_text(encoding='utf-8', errors='ignore').strip()
    except Exception:
        persona = ''

    # Memory recall block
    recent_lines = []
    try:
        rr = recall_recent(k=30)
        # support dict or list shapes
        if isinstance(rr, dict):
            items = rr.get('items') or rr.get('rows') or rr.get('memories') or []
        elif isinstance(rr, list):
            items = rr
        else:
            items = []

        for it in items:
            if isinstance(it, dict):
                txt = (it.get('text') or it.get('content') or '').strip()
            else:
                txt = str(it).strip()
            if txt:
                recent_lines.append(txt)
    except Exception:
        recent_lines = []

    out = []
    if persona:
        out.append('=== ELI PERSONA (source: eli/cognition/persona.txt) ===')
        out.append(persona)
    if recent_lines:
        out.append('\n=== RECENT MEMORY ===')
        out.extend(f'- {x}' for x in recent_lines)
    if user_message:
        out.append('\n=== USER MESSAGE ===')
        out.append(user_message)
    return '\n'.join(out).strip()

def _eli_build_context_fallback_guard(value):
    if value is None:
        return ""
    return value
