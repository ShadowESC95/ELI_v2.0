"""Frozen-app entry point for PyInstaller builds.

The console scripts in pyproject.toml (`eli = eli.gui.app:main`) are used for
source/venv installs; PyInstaller needs a real script file. This wrapper is
that script and nothing more — all launch logic stays in eli.gui.app so the
frozen build and the source install run identical code.

multiprocessing.freeze_support() must run before anything else: ELI spawns
helper processes (import smoke tests, sandboxed code runs) and without it a
frozen child process on Windows/macOS re-executes the whole GUI.
"""
import multiprocessing
import sys

multiprocessing.freeze_support()

from eli.gui.app import main  # noqa: E402  (freeze_support must precede app imports)

if __name__ == "__main__":
    sys.exit(main())
