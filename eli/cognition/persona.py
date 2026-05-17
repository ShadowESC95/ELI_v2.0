"""
Canonical persona authority for ELI.

Base persona:
    eli/cognition/persona.txt

Dynamic overlay:
    eli/cognition/persona.auto.txt

The dynamic overlay is intended to be regenerated from habits,
reflection, self-improvement, memory summaries, or other local runtime
signals. No user-specific hardcoded names belong in this module.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

_PERSONA_DIR = Path(__file__).resolve().parent
_PERSONA_FILE = Path(
    os.environ.get("ELI_PERSONA_FILE", str(_PERSONA_DIR / "persona.txt"))
).expanduser().resolve()
_PERSONA_AUTO_FILE = Path(
    os.environ.get("ELI_PERSONA_AUTO_FILE", str(_PERSONA_DIR / "persona.auto.txt"))
).expanduser().resolve()

_cached_persona: Optional[str] = None
_cached_signature: Optional[tuple] = None


def _clean_persona(raw: str) -> str:
    clean_lines = []
    in_template_block = False
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if stripped.upper().startswith(("PARAMETER ", "FROM ")):
            continue
        if stripped.upper().startswith("TEMPLATE "):
            in_template_block = True
            continue
        if in_template_block:
            if '"""' in stripped:
                in_template_block = False
            continue
        if stripped.startswith("# Model parameters") or stripped.startswith("# Template for conversation"):
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines).strip()


def _sanitize_auto_persona_text(text: str) -> str:
    text = text or ""

    line_rules = [
        (r'(?m)^- Runtime status:.*$', '- Runtime status: sanitized'),
        (r'(?m)^- Cognition runtime:.*$', '- Cognition runtime: sanitized'),
        (r'(?m)^- Memory recall:.*$', '- Memory recall: sanitized'),
    ]
    for patt, repl in line_rules:
        text = re.sub(patt, repl, text)

    inline_rules = [
        (r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', '<LOCAL_EMAIL>'),
        (r'(?<![A-Za-z0-9_])/(?:home|Users|mnt)/\S+', '<LOCAL_PATH>'),
        (r'\b[A-Za-z]:\\\S+', '<LOCAL_PATH>'),
    ]
    for patt, repl in inline_rules:
        text = re.sub(patt, repl, text)

    cleaned_lines = []
    for line in text.splitlines():
        low = line.lower()
        if any(tok in low for tok in ("script_exec_proposal", "proposal_id")):
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    return text


def base_path() -> Path:
    return _PERSONA_FILE


def auto_path() -> Path:
    return _PERSONA_AUTO_FILE


def _fallback_persona() -> str:
    return (
        "You are ELI, a local reasoning and automation assistant. "
        "Be direct, accurate, grounded, privacy-preserving, and useful."
    )


def _file_signature(path: Path) -> tuple:
    try:
        st = path.stat()
        return (True, int(st.st_mtime_ns), int(st.st_size))
    except FileNotFoundError:
        return (False, -1, -1)


def _read_raw(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


def read_base_persona() -> str:
    return _clean_persona(_read_raw(_PERSONA_FILE))


def read_auto_persona() -> str:
    return _clean_persona(_read_raw(_PERSONA_AUTO_FILE))


def _compose_persona() -> str:
    base = read_base_persona()
    auto = read_auto_persona()

    if base and auto:
        return (
            f"{base}\n\n"
            "# Auto-updating runtime persona overlay\n"
            "# Generated from habits, reflection, self-improvement, and runtime signals.\n\n"
            f"{auto}"
        ).strip()

    if base:
        return base.strip()

    if auto:
        return auto.strip()

    return _fallback_persona()


def get_persona() -> str:
    global _cached_persona, _cached_signature
    sig = (_file_signature(_PERSONA_FILE), _file_signature(_PERSONA_AUTO_FILE))
    if _cached_persona is None or _cached_signature != sig:
        _cached_persona = _compose_persona()
        _cached_signature = sig
    return _cached_persona or _fallback_persona()


def reload() -> str:
    global _cached_persona, _cached_signature
    _cached_persona = None
    _cached_signature = None
    return get_persona()


def write_base_persona(text: str) -> str:
    _PERSONA_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PERSONA_FILE.write_text((text or "").rstrip() + "\n", encoding="utf-8")
    return reload()


def write_auto_persona(text: str) -> str:
    _PERSONA_AUTO_FILE.parent.mkdir(parents=True, exist_ok=True)
    clean = _sanitize_auto_persona_text((text or "").rstrip() + "\n")
    _PERSONA_AUTO_FILE.write_text(clean, encoding="utf-8")
    return reload()

def clear_auto_persona() -> str:
    if _PERSONA_AUTO_FILE.exists():
        _PERSONA_AUTO_FILE.unlink()
    return reload()


def append_preference(pref: str) -> bool:
    pref = (pref or "").strip()
    if not pref:
        return False

    marker = "## User Preferences (Auto-Updated)"
    current = _read_raw(_PERSONA_AUTO_FILE).rstrip()

    if marker in current:
        new_text = f"{current}\n- {pref}\n"
    else:
        if current:
            current += "\n\n"
        new_text = f"{current}{marker}\n- {pref}\n"

    write_auto_persona(new_text)
    return True


def get_preferences() -> list[str]:
    content = read_auto_persona()
    marker = "## User Preferences (Auto-Updated)"
    if marker not in content:
        return []
    section = content.split(marker, 1)[1]
    out: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("-"):
            out.append(stripped.lstrip("- ").strip())
    return out


def update_auto_sections(sections: Mapping[str, Any]) -> str:
    lines = [
        "# Auto-updated persona overlay",
        "# Generated from habits, reflection, self-improvement, memory, and runtime signals.",
        "",
    ]

    for key, value in sections.items():
        if value is None:
            continue

        title = str(key).strip()
        if not title:
            continue

        lines.append(f"## {title}")

        if isinstance(value, str):
            val = value.strip()
            if val:
                lines.append(val)
        elif isinstance(value, (list, tuple, set)):
            added = False
            for item in value:
                item_s = str(item).strip()
                if item_s:
                    lines.append(f"- {item_s}")
                    added = True
            if not added:
                lines.append("- none")
        else:
            val = str(value).strip()
            lines.append(val if val else "- none")

        lines.append("")

    return write_auto_persona("\n".join(lines).rstrip() + "\n")


def status() -> Dict[str, Any]:
    persona = get_persona()
    prefs = get_preferences()
    return {
        "ok": True,
        "module": "persona",
        "mode": "active",
        "base_file": str(_PERSONA_FILE),
        "auto_file": str(_PERSONA_AUTO_FILE),
        "base_exists": _PERSONA_FILE.exists(),
        "auto_exists": _PERSONA_AUTO_FILE.exists(),
        "loaded": bool(persona),
        "length": len(persona),
        "preferences_count": len(prefs),
    }


__all__ = ["Persona", "base_path",
    "auto_path",
    "read_base_persona",
    "read_auto_persona",
    "get_persona",
    "reload",
    "write_base_persona",
    "write_auto_persona",
    "clear_auto_persona",
    "append_preference",
    "get_preferences",
    "update_auto_sections",
    "status", "Persona"]


# --- Added load_persona for compatibility with audit ---
_persona_singleton = None

def load_persona(reload: bool = False):
    """Load or reload the global persona instance."""
    global _persona_singleton
    if _persona_singleton is None or reload:
        _persona_singleton = Persona()
        _persona_singleton.load_from_db()
    return _persona_singleton


# --- Production Persona class with auto-update support ---
class Persona:
    """
    Full persona manager with auto-update from runtime signals.
    Integrates with persona.auto.txt and update_auto_sections().
    """
    def __init__(self):
        self._persona_text = None
        self._auto_sections = {}
        self._preferences = []
        self.load_from_db()

    def load_from_db(self):
        """Load the current persona (base + auto overlay)."""
        self._persona_text = get_persona()
        self._auto_sections = self._parse_auto_sections()
        self._preferences = get_preferences()
        return self

    def _parse_auto_sections(self) -> dict:
        """Parse the auto persona file into sections."""
        auto_text = read_auto_persona()
        sections = {}
        current_section = None
        for line in auto_text.splitlines():
            line = line.strip()
            if line.startswith('## '):
                current_section = line[3:].strip()
                sections[current_section] = []
            elif current_section and line and not line.startswith('#'):
                sections[current_section].append(line)
        return sections

    def get_persona(self) -> str:
        """Return the full persona text (base + auto overlay)."""
        if self._persona_text is None:
            self.load_from_db()
        return self._persona_text

    def update_auto_sections(self, sections: dict) -> bool:
        """
        Update auto persona sections.
        Sections dict: { "section_title": "text" or ["item1","item2"] }
        """
        result = update_auto_sections(sections)
        self.load_from_db()  # reload
        return True

    def add_preference(self, pref: str) -> bool:
        """Add a user preference to the auto persona."""
        result = append_preference(pref)
        self.load_from_db()
        return result

    def get_preferences(self) -> list:
        """Return current user preferences."""
        return self._preferences

    def get_auto_sections(self) -> dict:
        """Return parsed auto sections."""
        return self._auto_sections

    def refresh(self):
        """Reload persona from disk (useful after external changes)."""
        self.load_from_db()
        return self

    def __str__(self):
        return f"<Persona: {len(self.get_persona())} chars, {len(self._preferences)} preferences>"
