from __future__ import annotations

from eli.plugins.base.base import Plugin


class QuickNotesPlugin(Plugin):
    """The notes plugin's actions are ELI's own NEW_NOTE / SEARCH_NOTES / LIST_NOTES.

    It kept a second copy of them, writing to its own folder, and the executor answered those
    actions first, so it never ran. Notes have one owner now: the executor's actions and the one
    notes folder (paths.notes_dir) that WRITE_NOTE writes to as well."""
    name = "notes"
    description = "Markdown notes with full-text search"

    def __init__(self):
        self.actions = {
            "new_note": self.new_note,
            "search_notes": self.search_notes,
            "list_notes": self.list_notes,
        }
        super().__init__()

    @staticmethod
    def _action(action: str, args: dict) -> dict:
        from eli.execution.executor_enhanced import execute
        return execute(action, dict(args or {}))

    def new_note(self, args: dict) -> dict:
        return self._action("NEW_NOTE", args)

    def search_notes(self, args: dict) -> dict:
        return self._action("SEARCH_NOTES", args)

    def list_notes(self, args: dict) -> dict:
        return self._action("LIST_NOTES", args)
