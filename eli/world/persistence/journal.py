from __future__ import annotations
from pathlib import Path
from time import strftime

JOURNAL_PATH = Path("artifacts/world/journal/eli_world_journal.md")

def append_journal_entry(title: str, body: str, source: str = "eli_world") -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = strftime("%Y-%m-%d %H:%M:%S")
    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## {stamp} — {title}\n\n")
        f.write(f"Source: `{source}`\n\n")
        f.write(body.strip() + "\n")
