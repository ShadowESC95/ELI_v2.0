"""PyInstaller runtime hook — pin a coherent, writable ELI root for frozen builds.

ELI treats its project root as a self-contained tree (config/, models/,
artifacts/ live beside the eli/ package; see eli/core/paths.py and
eli/core/portable_paths.py). The launchers for source installs (RUN_ELI.sh,
bin/elix, eli.gui.app:main) all pin ELI_PROJECT_ROOT + the data/config/models
dirs before the app boots. This hook does the same job for frozen bundles.

Policy: the root is ALWAYS the per-user ELI_v2 directory —
    Windows : %LOCALAPPDATA%\\ELI_v2
    macOS   : ~/Library/Application Support/ELI_v2
    Linux   : ~/.local/share/ELI_v2
— the SAME location previous ELI releases (portable installs, the old
AppImage) used, so models, settings and conversation data carry straight
over on upgrade. It is also the only safe choice everywhere: the AppImage
mount is read-only, writing inside a macOS .app breaks its codesign seal,
and burying models under Program Files-style install dirs hides them from
the user and loses them on uninstall.

First launch (and each version upgrade) seeds the root from the bundle:
the eli/ source tree (ELI self-inspects its own code), api/, config
templates, blueprints and manifests. User state — config/settings.json,
models/, artifacts/ — is NEVER overwritten.

Explicit ELI_PROJECT_ROOT / ELI_*_DIR environment variables always win —
the hook only fills in what the user has not set.
"""
import os
import shutil
import sys
from pathlib import Path


def _force_utf8_streams() -> None:
    """ELI prints unicode (emoji/dashes) throughout. Windows consoles default
    to cp1252 and a single print at import time then kills the whole app with
    UnicodeEncodeError (killed ELI-Server.exe + the CI selftest). Frozen
    builds always run with UTF-8 streams, replacing unmappable characters."""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _suppress_child_console_windows() -> None:
    """Windowed Windows builds: every console-based child process (powershell
    audio playback in tts_router, nvidia-smi polling, clipboard probes)
    otherwise FLASHES a console window on screen. Default all subprocess
    spawns to CREATE_NO_WINDOW; callers that explicitly pass creationflags
    (e.g. an intentional visible terminal) are respected."""
    if sys.platform != "win32":
        return
    import subprocess
    _orig_init = subprocess.Popen.__init__

    def _no_window_init(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return _orig_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _no_window_init


if getattr(sys, "frozen", False):
    _force_utf8_streams()
    _suppress_child_console_windows()

# Directories/files seeded into the per-user root. eli/ and api/ are the
# source trees (introspection + plugin discovery read them from disk); the
# rest are runtime data the app resolves via PROJECT_ROOT.
_SEED_TREES = ("eli", "api", "config", "blueprints", "docs", "packaging/desktop", "tts_piper")
_SEED_FILES = (
    "pyproject.toml",
    "capability_manifest.json",
    "capability_inventory.generated.json",
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
)
# Merge-only trees: add missing files, never clobber what the user has
# (config/ holds live settings.json, tokens, certs).
_PRESERVE = ("config",)


def _warn(msg: str) -> None:
    """stderr is None in windowed Windows builds — writing to it crashed the
    boot (v2.1.7); never let a diagnostic message take the app down."""
    try:
        if sys.stderr is not None:
            sys.stderr.write(msg)
    except Exception:
        pass


def _bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))


def _app_version(bundle: Path) -> str:
    try:
        text = (bundle / "pyproject.toml").read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("version") and '"' in line:
                return line.split('"')[1]
    except Exception:
        pass
    return "unknown"


def _user_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "ELI_v2"


def _seed(bundle: Path, root: Path) -> None:
    version = _app_version(bundle)
    marker = root / ".eli_frozen_seed_version"
    try:
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == version:
            return
    except Exception:
        pass

    root.mkdir(parents=True, exist_ok=True)
    for rel in _SEED_TREES:
        src = bundle / rel
        if not src.is_dir():
            continue
        dst = root / rel
        if rel in _PRESERVE and dst.exists():
            for f in src.rglob("*"):
                if f.is_file():
                    target = dst / f.relative_to(src)
                    if not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, target)
        else:
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst, dirs_exist_ok=True)
    for rel in _SEED_FILES:
        src = bundle / rel
        if src.is_file():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, root / rel)
    for rel in ("models", "artifacts"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    try:
        marker.write_text(version, encoding="utf-8")
    except Exception:
        pass


def _pin_frozen_root() -> None:
    if not getattr(sys, "frozen", False):
        return
    if os.environ.get("ELI_PROJECT_ROOT"):
        return  # launcher/user already decided — respect it

    root = _user_root()
    try:
        _seed(_bundle_dir(), root)
    except Exception as exc:  # pragma: no cover — first-run disk issues
        _warn(
            f"[ELI] could not prepare user data root {root}: {exc}\n"
            f"[ELI] set ELI_PROJECT_ROOT to a writable ELI directory and relaunch.\n"
        )
        return

    # GPU pack (see eli_gpu_pack.py): a downloaded CUDA/Vulkan build of
    # llama_cpp in the user root shadows the bundled CPU build. llama_cpp is
    # collected as on-disk source (module_collection_mode in ELI.spec), so
    # plain sys.path priority decides which copy imports. Activation REQUIRES
    # the install-time verification marker: an unverified/broken pack must
    # never brick the app (v2.1.4 crashed at every boot when a CUDA pack
    # missing its runtime libs shadowed the working CPU copy).
    gpu_dir = root / "runtime" / "gpu"
    if (gpu_dir / "llama_cpp").is_dir():
        if (gpu_dir / ".gpu_pack_ok").is_file():
            sys.path.insert(0, str(gpu_dir))
            try:
                import eli_gpu_pack
                eli_gpu_pack.preload_native_libs(gpu_dir)
            except Exception:
                pass
        else:
            _warn(
                "[ELI] ignoring unverified GPU pack (missing .gpu_pack_ok) — "
                "running on CPU; reinstall with: ELI --install-gpu-pack --force\n"
            )

    os.environ["ELI_PROJECT_ROOT"] = str(root)
    os.environ.setdefault("ELI_HOME", str(root))
    os.environ.setdefault("ELI_DATA_DIR", str(root / "artifacts"))
    # Some subsystems (image engine runtime_paths) key on ELI_ARTIFACTS_DIR
    # rather than ELI_DATA_DIR — export both names for the same directory.
    os.environ.setdefault("ELI_ARTIFACTS_DIR", str(root / "artifacts"))
    os.environ.setdefault("ELI_CONFIG_DIR", str(root / "config"))
    os.environ.setdefault("ELI_MODELS_DIR", str(root / "models"))
    # Custom agents are created at runtime; both the GUI writer and the
    # agent-bus loader honor this variable (module-relative default is
    # read-only in frozen builds).
    os.environ.setdefault("ELI_CUSTOM_AGENTS_DIR", str(root / "eli" / "brain" / "agents" / "custom"))
    # Additional env names honored by individual subsystems whose defaults
    # are module-relative (read-only when frozen).
    os.environ.setdefault("ELI_ROOT", str(root))                      # habits_memory_db
    os.environ.setdefault("ELI_DOC_DIR", str(root / "eli_docs"))      # executor document actions


_pin_frozen_root()
