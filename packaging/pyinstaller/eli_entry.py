"""Frozen-app entry point for PyInstaller builds.

The console scripts in pyproject.toml (`eli = eli.gui.app:main`) are used for
source/venv installs; PyInstaller needs a real script file. This wrapper is
that script; all launch logic stays in eli.gui.app / api.server so the frozen
build and a source install run identical code.

Modes:
  (default)     the ELI GUI (eli.gui.app:main)
  --server      the phone/web server (api.server:main) — also the default when
                the executable is named ELI-Server (second EXE in ELI.spec,
                built console=True so server logs + the phone URL are visible)
  --selftest    import the heavy runtime stack and exit 0/1. CI runs this on
                the built bundle for every platform: it catches broken frozen
                imports (missing hidden imports, syntax errors from a Python
                version mismatch) BEFORE an artifact can reach a release.
                Failures are also written to eli_selftest_error.log because a
                windowed Windows exe has no stderr.

multiprocessing.freeze_support() must run before anything else: ELI spawns
helper processes (import smoke tests, sandboxed code runs) and without it a
frozen child process on Windows/macOS re-executes the whole GUI.
"""
import multiprocessing
import sys
from pathlib import Path

multiprocessing.freeze_support()


def _selftest() -> int:
    import traceback
    try:
        import eli                                    # noqa: F401
        import eli.gui.eli_pro_audio_gui_v2_0 as gui  # full GUI import chain (Qt, plugins, memory)
        import api.server                             # noqa: F401  web/phone server stack
        import llama_cpp                              # noqa: F401  native inference libs load
        print(f"selftest OK — ELI {gui.APP_VERSION}, python {sys.version.split()[0]}")
        return 0
    except Exception:
        tb = traceback.format_exc()
        sys.stderr.write(tb)
        try:  # windowed exes have no visible stderr — leave a breadcrumb file
            Path("eli_selftest_error.log").write_text(tb, encoding="utf-8")
        except Exception:
            pass
        return 1


def _mode() -> str:
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return "selftest"
    exe = Path(sys.argv[0]).stem.lower()
    if "--server" in argv or exe.endswith("server"):
        return "server"
    return "gui"


if __name__ == "__main__":
    mode = _mode()
    if mode == "selftest":
        sys.exit(_selftest())
    elif mode == "server":
        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--server"]
        from api.server import main as server_main
        sys.exit(server_main())
    else:
        from eli.gui.app import main
        sys.exit(main())
