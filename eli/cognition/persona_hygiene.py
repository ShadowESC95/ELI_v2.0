"""
brain.awareness.persona_hygiene
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Cleans up the persona auto-overlay (persona.auto.txt) by deduplicating
entries, pruning stale patterns, and capping section sizes.

Called from boot_awareness() and optionally from SELF_IMPROVE.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

log = logging.getLogger(__name__)

# Max entries per auto-section before oldest get pruned
_MAX_ENTRIES_PER_SECTION = 8


def clean_auto_persona(repo_root: Optional[Path] = None) -> Dict[str, object]:
    """
    Read persona.auto.txt, deduplicate entries within each section,
    prune stale/noisy patterns, write back, return stats.
    """
    if repo_root is None:
        try:
            from eli.core.paths import get_paths
            repo_root = get_paths().project_root
        except Exception:
            repo_root = Path(__file__).resolve().parents[2]

    from eli.core.paths import persona_auto_path
    auto_path = persona_auto_path()
    if not auto_path.exists():
        return {"ok": True, "action": "persona_hygiene", "changed": False}

    original = auto_path.read_text(encoding="utf-8", errors="replace")
    sections = _parse_sections(original)
    changed = False

    for title, entries in sections.items():
        before = len(entries)
        entries = _dedup(entries)
        entries = _prune_noise(entries)
        entries = entries[-_MAX_ENTRIES_PER_SECTION:]  # keep newest
        sections[title] = entries
        if len(entries) != before:
            changed = True

    if not changed:
        return {"ok": True, "action": "persona_hygiene", "changed": False}

    rebuilt = _rebuild(sections)
    from eli.cognition.persona import write_auto_persona
    write_auto_persona(rebuilt)
    log.info("persona_hygiene: cleaned auto-overlay (%d sections)", len(sections))
    return {"ok": True, "action": "persona_hygiene", "changed": True, "sections": len(sections)}


def _parse_sections(text: str) -> Dict[str, List[str]]:
    """Parse ## Section headers and their bullet entries."""
    sections: Dict[str, List[str]] = {}
    current_title: Optional[str] = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current_title = stripped[3:].strip()
            if current_title not in sections:
                sections[current_title] = []
        elif stripped.startswith("- ") and current_title is not None:
            sections[current_title].append(stripped[2:].strip())
        # Skip comment lines and blank lines
    return sections


def _dedup(entries: List[str]) -> List[str]:
    """Remove exact duplicates, preserving order (keep last occurrence)."""
    seen: Set[str] = set()
    result: List[str] = []
    for entry in reversed(entries):
        normalized = entry.strip().lower()
        if normalized not in seen:
            seen.add(normalized)
            result.append(entry)
    result.reverse()
    return result


def _prune_noise(entries: List[str]) -> List[str]:
    """Remove entries that are known noise patterns."""
    noise_patterns = [
        # Repeated daemon started messages
        re.compile(r"^proactive daemon started$", re.I),
        # Repeated generic test errors without useful context
        re.compile(r"^enterprise test error$", re.I),
        # Pipe IDs with no context
        re.compile(r"^this:\s*pipe_\d+$", re.I),
        # Proposal / placeholder contamination
        re.compile(r".*script_exec_proposal.*", re.I),
        re.compile(r".*proposal_id.*", re.I),
        re.compile(r".*<local_path>.*", re.I),
    ]
    result: List[str] = []
    for entry in entries:
        text = entry.strip()
        if any(p.match(text) for p in noise_patterns):
            continue
        result.append(entry)
    return result


def _rebuild(sections: Dict[str, List[str]]) -> str:
    """Rebuild the auto-overlay text from sections."""
    lines = [
        "# Auto-updated persona overlay",
        "# Generated from habits, reflection, self-improvement, memory, and runtime signals.",
        "",
    ]
    for title, entries in sections.items():
        lines.append(f"## {title}")
        if entries:
            for entry in entries:
                lines.append(f"- {entry}")
        else:
            lines.append("- (none)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
