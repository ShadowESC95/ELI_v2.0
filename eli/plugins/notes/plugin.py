from __future__ import annotations

import re
import time
from pathlib import Path
from typing import List, Dict

from eli.plugins.base.base import Plugin


class QuickNotesPlugin(Plugin):
    name = "notes"
    description = "Markdown notes with full-text search"

    def __init__(self):
        self.actions = {
            "new_note": self.new_note,
            "search_notes": self.search_notes,
            "list_notes": self.list_notes,
        }
        super().__init__()

    def _notes_dir(self) -> Path:
        try:
            from eli.core.paths import get_paths
            d = get_paths().artifacts_dir / "notes"
        except Exception:
            d = Path.home() / ".eli" / "notes"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def new_note(self, args: dict) -> dict:
        title = (args.get("title") or args.get("name") or "").strip()
        content = (args.get("content") or args.get("text") or args.get("body") or "").strip()
        if not content:
            return {"ok": False, "content": "No content provided.", "response": "Provide note content."}
        if not title:
            title = content[:50].replace("\n", " ").strip()
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower())[:40].strip("_")
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = f"{ts}_{slug}.md"
        note_path = self._notes_dir() / fname
        note_path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        msg = f"Note saved: {fname}"
        return {"ok": True, "content": msg, "response": f"Saved note '{title}'.", "path": str(note_path)}

    def search_notes(self, args: dict) -> dict:
        query = (args.get("query") or args.get("q") or args.get("text") or "").strip().lower()
        if not query:
            return {"ok": False, "content": "No query.", "response": "Provide search terms."}
        results: List[Dict] = []
        for p in sorted(self._notes_dir().glob("*.md"), reverse=True):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if query in text.lower():
                first_line = text.split("\n")[0].lstrip("#").strip()
                results.append({
                    "file": p.name,
                    "title": first_line,
                    "preview": text[:300].replace("\n", " "),
                })
                if len(results) >= 10:
                    break
        if not results:
            return {"ok": True, "content": f"No notes found for '{query}'.",
                    "response": f"Nothing found for '{query}'.", "results": []}
        lines = [f"Found {len(results)} note(s) for '{query}':"]
        for r in results:
            lines.append(f"  [{r['file']}] {r['title']}")
        return {"ok": True, "content": "\n".join(lines), "response": "\n".join(lines), "results": results}

    def list_notes(self, args: dict) -> dict:
        files = sorted(self._notes_dir().glob("*.md"), reverse=True)[:20]
        if not files:
            return {"ok": True, "content": "No notes yet.", "response": "No notes yet.", "notes": []}
        lines = [f"Notes ({len(files)}):"]
        notes = []
        for p in files:
            try:
                first_line = p.read_text(encoding="utf-8", errors="ignore").split("\n")[0].lstrip("#").strip()
            except Exception:
                first_line = p.name
            lines.append(f"  {p.name[:30]:30s}  {first_line[:60]}")
            notes.append({"file": p.name, "title": first_line})
        return {"ok": True, "content": "\n".join(lines), "response": "\n".join(lines), "notes": notes}
