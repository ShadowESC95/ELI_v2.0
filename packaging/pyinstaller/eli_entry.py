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
  --selftest    boot the runtime stack + verify every mutable path resolves
                OUTSIDE the read-only bundle, then exit 0/1. CI runs this on
                the built bundle for every platform before anything ships.
  -c / -m       python-compatible passthrough. ELI spawns
                `sys.executable -c "…"` helpers (import smoke tests, sandbox
                probes); in a frozen app sys.executable is ELI itself, and
                without this the helpers re-launched whole GUI instances
                (the "installer started the app two more times" bug).

multiprocessing.freeze_support() must run before anything else: ELI spawns
helper processes and without it a frozen child on Windows/macOS re-executes
the whole GUI.
"""
import multiprocessing
import os
import sys
from pathlib import Path

multiprocessing.freeze_support()

# python -c / -m passthrough for self-spawned helpers (see module docstring).
if len(sys.argv) >= 2 and sys.argv[1] == "-c":
    _code = sys.argv[2] if len(sys.argv) >= 3 else ""
    sys.argv = [sys.argv[0]] + sys.argv[3:]
    exec(compile(_code, "<frozen -c>", "exec"), {"__name__": "__main__"})
    sys.exit(0)
if len(sys.argv) >= 3 and sys.argv[1] == "-m":
    import runpy
    _mod = sys.argv[2]
    sys.argv = [sys.argv[0]] + sys.argv[3:]
    runpy.run_module(_mod, run_name="__main__", alter_sys=True)
    sys.exit(0)


def _assert_paths_outside_bundle() -> None:
    """Every mutable path must resolve outside the read-only bundle — the
    v2.1.0 AppImage shipped with vector store / voice mirror / pending-state
    writes all pointed into the squashfs mount."""
    if not getattr(sys, "frozen", False):
        return
    from eli.core import paths as _paths
    from eli.runtime import grounded_remediation as _grem
    bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    exe_dir = Path(sys.executable).resolve().parent
    from eli.cognition import persona as _persona
    from eli.tools.image_engine import runtime_paths as _img_paths
    checks = {
        "project_root": Path(_paths.project_root()),
        "data_dir": Path(_paths.data_dir()),
        "config_dir": Path(_paths.config_dir()),
        "models_dir": Path(_paths.models_dir()),
        "remediation_root": _grem._root(),
        # runtime WRITE targets that shipped broken once each — keep gated
        "persona_auto_file": Path(_persona._PERSONA_AUTO_FILE),
        "image_artifacts_dir": Path(_img_paths.artifacts_dir()),
        "custom_agents_dir": Path(os.environ.get("ELI_CUSTOM_AGENTS_DIR", "")) if os.environ.get("ELI_CUSTOM_AGENTS_DIR") else Path(_paths.project_root()) / "eli",
    }
    for name, p in checks.items():
        rp = p.resolve()
        for ro in (bundle, exe_dir):
            if rp == ro or str(rp).startswith(str(ro) + os.sep):
                raise RuntimeError(
                    f"selftest: {name} resolves inside the read-only bundle: {rp}"
                )
    probe = Path(_paths.data_dir()) / ".selftest_write_probe"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    if os.environ.get("ELI_REQUIRE_VOICES") == "1":
        if not list((bundle / "tts_piper" / "piper").glob("*.onnx")):
            raise RuntimeError("selftest: no Piper voices bundled (tts_piper/piper/*.onnx)")


def _selftest() -> int:
    import traceback
    try:
        import eli                                    # noqa: F401
        # Replicate the real launch order: eli.gui.app:main runs the DB/schema
        # bootstrap BEFORE importing the GUI module (whose import opens the
        # memory DB).
        from eli.core.init_data import bootstrap_once
        bootstrap_once()
        import eli.gui.eli_pro_audio_gui_v2_0 as gui  # full GUI import chain (Qt, plugins, memory)
        import api.server                             # noqa: F401  web/phone server stack
        import llama_cpp                              # noqa: F401  native inference libs load
        # llama_cpp must import from REAL files on disk (module_collection_mode
        # "py") or the GPU pack cannot shadow it via sys.path.
        if getattr(sys, "frozen", False) and not Path(llama_cpp.__file__).is_file():
            raise RuntimeError(
                f"llama_cpp imported from the frozen archive, not from disk "
                f"({llama_cpp.__file__}) — GPU pack shadowing would be broken"
            )
        _assert_paths_outside_bundle()
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
    if "--install-gpu-pack" in argv:
        return "gpu-pack"
    exe = Path(sys.argv[0]).stem.lower()
    if "--server" in argv or exe.endswith("server"):
        return "server"
    return "gui"


if __name__ == "__main__":
    mode = _mode()
    if mode == "selftest":
        sys.exit(_selftest())
    elif mode == "gpu-pack":
        import eli_gpu_pack
        sys.exit(eli_gpu_pack.install([a for a in sys.argv[1:] if a != "--install-gpu-pack"]))
    elif mode == "server":
        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--server"]
        from api.server import main as server_main
        sys.exit(server_main())
    else:
        from eli.gui.app import main
        sys.exit(main())
