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
        "code_examiner_root": __import__("eli.runtime.self_improvement", fromlist=["PROJECT_ROOT"]).PROJECT_ROOT,
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


def _user_root() -> Path:
    return Path(os.environ.get("ELI_PROJECT_ROOT", "") or "")


def _fresh_start(argv: list[str]) -> int:
    """Wipe per-user ELI state for a clean-slate install (game-save reset).

    Removes settings, memory DBs, artifacts and the seeded code tree, so the
    next launch reseeds + onboards from scratch. Downloaded AI models and the
    GPU pack are KEPT (static downloads, no state) unless --purge-models.
    """
    import shutil
    root = _user_root()
    if not str(root) or not root.is_dir():
        print(f"[fresh-start] nothing to reset ({root or 'no ELI data root'})")
        return 0
    purge_models = "--purge-models" in argv
    keep = set() if purge_models else {"models", "runtime"}
    if "--yes" not in argv:
        kept = "nothing kept" if purge_models else "keeping downloaded models + GPU pack"
        answer = input(f"[fresh-start] wipe ELI data in {root} ({kept})? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("[fresh-start] cancelled")
            return 1
    for item in root.iterdir():
        if item.name in keep:
            continue
        (shutil.rmtree if item.is_dir() else os.unlink)(item)
    print(f"[fresh-start] done — ELI will set up fresh on next launch ({', '.join(sorted(keep)) or 'nothing'} kept)")
    return 0


def _desktop_files() -> dict[str, Path]:
    apps = Path.home() / ".local" / "share" / "applications"
    return {
        "eli": apps / "eli-v2.desktop",
        "server": apps / "eli-v2-server.desktop",
        "uninstall": apps / "eli-v2-uninstall.desktop",
        "icon": Path.home() / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "eli-v2.png",
    }


def _integrate(quiet: bool = False) -> int:
    """Linux: install applications-menu entries (ELI, Server, Uninstall) that
    point at THIS AppImage, with THIS version's icon — replacing any stale
    entries from older installs."""
    import shutil
    if sys.platform != "linux":
        print("[integrate] only needed on Linux")
        return 0
    appimage = os.environ.get("APPIMAGE", "") or sys.executable
    bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    files = _desktop_files()
    # replace stale entries from any older install
    for old in files["eli"].parent.glob("eli*.desktop"):
        old.unlink(missing_ok=True)
    files["icon"].parent.mkdir(parents=True, exist_ok=True)
    src_icon = bundle / "packaging" / "desktop" / "eli-256.png"
    if src_icon.is_file():
        shutil.copy2(src_icon, files["icon"])
    files["eli"].parent.mkdir(parents=True, exist_ok=True)
    entries = {
        "eli": ("ELI v2.0", f'"{appimage}"', "ELI — private local AI assistant"),
        "server": ("ELI Server (phone & web)", f'"{appimage}" --server', "ELI phone/web server with console output"),
        "uninstall": ("Uninstall ELI v2.0", f'"{appimage}" --uninstall', "Remove ELI menu entries and optionally its data"),
    }
    for key, (name, execline, comment) in entries.items():
        files[key].write_text(
            "[Desktop Entry]\nType=Application\n"
            f"Name={name}\nComment={comment}\nExec={execline}\n"
            f"Icon={files['icon']}\nCategories=Utility;\nTerminal={'true' if key != 'eli' else 'false'}\n",
            encoding="utf-8",
        )
    if not quiet:
        print(f"[integrate] menu entries installed for {appimage}")
    return 0


def _uninstall() -> int:
    """Linux: remove menu entries; optionally wipe ELI data. The AppImage file
    itself is just a file — delete it afterwards if you want it gone."""
    import shutil
    import subprocess
    files = _desktop_files()
    for old in files["eli"].parent.glob("eli*.desktop"):
        old.unlink(missing_ok=True)
    files["icon"].unlink(missing_ok=True)
    root = _user_root()
    wipe = False
    ask = f"""
import sys
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv)
m = QMessageBox()
m.setWindowTitle("Uninstall ELI")
m.setText("ELI's menu entries have been removed.")
m.setInformativeText("Also delete ELI's data (settings, memory, downloaded models) in {root}?\\n\\nFinally, delete the .AppImage file itself to finish removal.")
yes = m.addButton("Delete data too", QMessageBox.AcceptRole)
m.addButton("Keep data", QMessageBox.RejectRole)
m.exec()
sys.exit(0 if m.clickedButton() is yes else 3)
"""
    try:
        wipe = subprocess.run([sys.executable, "-c", ask]).returncode == 0
    except Exception:
        answer = input(f"[uninstall] also delete ELI data in {root}? [y/N] ").strip().lower()
        wipe = answer in ("y", "yes")
    if wipe and str(root) and root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
        print(f"[uninstall] data removed: {root}")
    print("[uninstall] menu entries removed — delete the .AppImage file to finish")
    return 0


def _first_run_integrate_offer() -> None:
    """Linux AppImage first run: offer applications-menu integration once."""
    if sys.platform != "linux" or not os.environ.get("APPIMAGE"):
        return
    try:
        import subprocess
        root = _user_root()
        if not str(root):
            return
        marker = root / "runtime" / ".desktop_integrated"
        if marker.exists():
            return
        marker.parent.mkdir(parents=True, exist_ok=True)
        ask = """
import sys
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv)
m = QMessageBox()
m.setWindowTitle("ELI - desktop integration")
m.setText("Add ELI to your applications menu?")
m.setInformativeText("Creates launcher entries for ELI, ELI Server and Uninstall "
                     "pointing at this AppImage, with the current icon. Replaces "
                     "entries from older versions.")
yes = m.addButton("Add to menu (recommended)", QMessageBox.AcceptRole)
m.addButton("Not now", QMessageBox.RejectRole)
m.exec()
sys.exit(0 if m.clickedButton() is yes else 3)
"""
        if subprocess.run([sys.executable, "-c", ask]).returncode == 0:
            _integrate(quiet=True)
        marker.write_text("asked", encoding="utf-8")
    except Exception:
        pass


def _first_run_gpu_offer() -> None:
    """First-launch hardware chooser (frozen GUI builds, Windows/Linux).

    Asks once: enable GPU acceleration (NVIDIA→CUDA / AMD→Vulkan, auto-
    detected) or stay on CPU. Runs BEFORE anything imports llama_cpp, so an
    installed pack takes effect the same boot (sys.path shadowing) with no
    restart. The dialog + download run in ELI subprocesses (via the python
    `-c` passthrough above) because the main GUI later creates its own
    QApplication. Declining writes a marker and never asks again;
    `--install-gpu-pack` stays available. macOS is Metal out of the box.
    """
    if not getattr(sys, "frozen", False) or sys.platform == "darwin":
        return
    try:
        import subprocess
        root = Path(os.environ.get("ELI_PROJECT_ROOT", "") or "")
        if not str(root):
            return
        runtime = root / "runtime"
        marker = runtime / ".gpu_choice"
        if marker.exists() or (runtime / "gpu" / "llama_cpp").is_dir():
            return
        # Canonical detection — the SAME HardwareProfile install.sh's verify,
        # the smart-fit loader and the HARDWARE_PROFILE action use (NVIDIA
        # nvidia-smi, AMD rocm-smi/sysfs/registry). One source of truth.
        from eli.core.hardware_profile import detect_hardware
        hp = detect_hardware()
        runtime.mkdir(parents=True, exist_ok=True)
        if not hp.has_gpu:
            marker.write_text("cpu-no-gpu-hardware", encoding="utf-8")
            return
        name_l = (hp.gpu_name or "").lower()
        nvidia = "nvidia" in name_l or "geforce" in name_l or "rtx" in name_l or "gtx" in name_l
        amd = (not nvidia) and ("amd" in name_l or "radeon" in name_l)
        if not (nvidia or amd):
            marker.write_text(f"cpu-unsupported-gpu:{hp.gpu_name}", encoding="utf-8")
            return
        vendor = f"{hp.gpu_name} — {max(hp.total_vram_mb, hp.free_vram_mb) / 1024:.0f} GB VRAM"
        backend = "NVIDIA CUDA" if nvidia else "AMD Vulkan"
        size = "roughly 400-500 MB" if nvidia else "roughly 90 MB"
        ask = f"""
import sys
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv)
m = QMessageBox()
m.setWindowTitle("ELI - GPU acceleration")
m.setText("ELI detected: {vendor}")
m.setInformativeText("Enable {backend} acceleration now? This downloads the GPU "
                     "inference engine once ({size}). CPU mode always works; "
                     "you can enable GPU later by running ELI with --install-gpu-pack.")
yes = m.addButton("Enable GPU (recommended)", QMessageBox.AcceptRole)
m.addButton("Use CPU", QMessageBox.RejectRole)
m.exec()
sys.exit(0 if m.clickedButton() is yes else 3)
"""
        if subprocess.run([sys.executable, "-c", ask]).returncode != 0:
            marker.write_text("cpu-user-choice", encoding="utf-8")
            return
        download = """
import sys, threading
from PySide6.QtWidgets import QApplication, QProgressDialog
from PySide6.QtCore import Qt, QTimer
import eli_gpu_pack
app = QApplication(sys.argv)
dlg = QProgressDialog("Downloading the GPU acceleration pack...", None, 0, 0)
dlg.setWindowTitle("ELI - GPU acceleration")
dlg.setCancelButton(None)
dlg.setWindowModality(Qt.ApplicationModal)
dlg.setMinimumWidth(420)
dlg.show()
rc = {"v": 1}
t = threading.Thread(target=lambda: rc.__setitem__("v", eli_gpu_pack.install([])), daemon=True)
t.start()
timer = QTimer()
timer.timeout.connect(lambda: None if t.is_alive() else app.quit())
timer.start(300)
app.exec()
sys.exit(rc["v"])
"""
        rc = subprocess.run([sys.executable, "-c", download]).returncode
        if rc == 0 and (runtime / "gpu" / ".gpu_pack_ok").is_file():
            marker.write_text("gpu", encoding="utf-8")
            sys.path.insert(0, str(runtime / "gpu"))  # effective THIS boot
            import eli_gpu_pack as _gp
            _gp.preload_native_libs(runtime / "gpu")
        else:
            # no marker on failure — the offer returns next launch, and the
            # CLI path (--install-gpu-pack) is always available. The pack
            # installer already removed anything unverified.
            notice = """
import sys
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv)
QMessageBox.warning(None, "ELI - GPU acceleration",
    "The GPU pack could not be installed or verified on this machine, so ELI "
    "will run on CPU (fully functional). It will offer GPU again at next "
    "launch; you can also retry any time with:  ELI --install-gpu-pack")
"""
            subprocess.run([sys.executable, "-c", notice])
    except Exception:
        pass  # never block the GUI boot on the chooser


def _mode() -> str:
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return "selftest"
    if "--install-gpu-pack" in argv:
        return "gpu-pack"
    if "--remove-gpu-pack" in argv:
        return "gpu-pack-remove"
    if "--fresh-start" in argv:
        return "fresh-start"
    if "--integrate" in argv:
        return "integrate"
    if "--uninstall" in argv:
        return "uninstall"
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
    elif mode == "gpu-pack-remove":
        import os as _os
        import shutil as _shutil
        _gpu = Path(_os.environ.get("ELI_PROJECT_ROOT", "")) / "runtime" / "gpu"
        _marker = _gpu.parent / ".gpu_choice"
        _shutil.rmtree(_gpu, ignore_errors=True)
        _marker.unlink(missing_ok=True)
        print(f"[gpu-pack] removed {_gpu}; ELI runs on CPU and will offer GPU again at next launch")
        sys.exit(0)
    elif mode == "server":
        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--server"]
        from api.server import main as server_main
        sys.exit(server_main())
    elif mode == "fresh-start":
        sys.exit(_fresh_start(sys.argv[1:]))
    elif mode == "integrate":
        sys.exit(_integrate())
    elif mode == "uninstall":
        sys.exit(_uninstall())
    else:
        _first_run_gpu_offer()
        _first_run_integrate_offer()
        from eli.gui.app import main
        sys.exit(main())
