from __future__ import annotations
from pathlib import Path
from time import strftime

def journal_path() -> Path:
    """Absolute path to the world journal.

    Was a module-level Path("artifacts/world/journal/...") — relative to the
    CURRENT WORKING DIRECTORY, so the journal landed in a different place
    depending on where ELI was launched from, and in a packaged build tried to
    write to /artifacts and failed. storage.world_dir() already resolves this
    correctly for every install layout.
    """
    from eli.world.persistence.storage import world_dir
    return world_dir() / "journal" / "eli_world_journal.md"


def append_journal_entry(title: str, body: str, source: str = "eli_world") -> None:
    JOURNAL_PATH = journal_path()
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = strftime("%Y-%m-%d %H:%M:%S")
    with JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n\n## {stamp} — {title}\n\n")
        f.write(f"Source: `{source}`\n\n")
        f.write(body.strip() + "\n")
