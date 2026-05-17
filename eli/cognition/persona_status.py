from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[2]

CANONICAL_PERSONA_FILES = [
    PROJECT_ROOT / "eli" / "cognition" / "persona.txt",
    PROJECT_ROOT / "eli" / "cognition" / "persona.auto.txt",
]


def persona_status(include_contents: bool = False, max_chars: int = 20000) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []

    for p in CANONICAL_PERSONA_FILES:
        item: Dict[str, Any] = {
            "path": str(p.resolve()),
            "exists": p.exists(),
            "size_bytes": p.stat().st_size if p.exists() else 0,
        }

        if include_contents and p.exists():
            text = p.read_text(encoding="utf-8", errors="replace")
            item["content"] = text[:max_chars]
            item["truncated"] = len(text) > max_chars

        files.append(item)

    return {
        "project_root": str(PROJECT_ROOT),
        "persona_files": files,
    }


def format_persona_status(include_contents: bool = False) -> str:
    data = persona_status(include_contents=include_contents)

    lines = [
        "Grounded persona file scan:",
        "",
    ]

    for i, f in enumerate(data["persona_files"], 1):
        lines.append(f"{i}. {f['path']}")
        lines.append(f"   exists={f['exists']} size={f['size_bytes']} bytes")

        if include_contents and f.get("exists"):
            lines.append("")
            lines.append("```text")
            lines.append(f.get("content", ""))
            lines.append("```")
            if f.get("truncated"):
                lines.append("[truncated]")
            lines.append("")

    return "\n".join(lines).strip()
