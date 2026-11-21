"""Where ELI may write a file: the allow-roots CREATE_FILE checks (SecurityManager.is_path_allowed).

That check is the one part of this module a runtime path uses, so it is all that is left. The
command and app allowlists (is_command_allowed, safe_subprocess, is_app_allowed, read from
ELI_ALLOWED_CMDS / ELI_ALLOWED_APPS) were called only by tests, and building a manager logged
"shell commands are BLOCKED", which was never true of the live gate: commands are judged by
eli/execution/shell_gate.py.
"""
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple, List
import logging

logger = logging.getLogger(__name__)


class SecurityManager:
    """The folders ELI may write files in: the project, the home folder, and ELI_ALLOW_ROOTS."""

    def __init__(self):
        self.project_root = self._get_project_root()
        self.allowed_roots = self._get_allowed_roots()

    def _get_project_root(self) -> Path:
        """Get ELI project root"""
        root = os.environ.get("ELI_ROOT")
        if root:
            return Path(root).resolve()

        # Fallback: parent of this file
        return Path(__file__).resolve().parents[2]

    def _get_allowed_roots(self) -> List[Path]:
        """The project, home, and each ELI_ALLOW_ROOTS entry. Entries are split on os.pathsep (":" on
        Linux and macOS, ";" on Windows): a ":" split cut "C:\\work" in two."""
        roots = [self.project_root, Path.home().resolve()]

        extra = os.environ.get("ELI_ALLOW_ROOTS", "")
        for p in extra.split(os.pathsep):
            if p.strip():
                try:
                    roots.append(Path(p.strip()).expanduser().resolve())
                except Exception as e:
                    logger.warning(f"Invalid allowed root {p}: {e}")

        return roots

    def is_path_allowed(self, path_str: str) -> Tuple[bool, Optional[Path]]:
        """Check if a path is within allowed roots"""
        try:
            path = Path(path_str).expanduser().resolve()

            for root in self.allowed_roots:
                try:
                    path.relative_to(root)
                    return True, path
                except ValueError:
                    continue

            return False, path

        except Exception as e:
            logger.error(f"Path validation error for {path_str}: {e}")
            return False, None


@lru_cache(maxsize=1)
def _manager_for(project_root: str, allow_roots: str, home: str) -> SecurityManager:
    return SecurityManager()


def get_security_manager() -> SecurityManager:
    """The SecurityManager for the current ELI_ROOT, ELI_ALLOW_ROOTS and home folder: built once for
    them, not on every file written, and built again when one of them changes."""
    return _manager_for(os.environ.get("ELI_ROOT", ""), os.environ.get("ELI_ALLOW_ROOTS", ""), str(Path.home()))
