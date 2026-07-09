"""PyInstaller runtime hook — pin a coherent, writable ELI root for frozen builds.

ELI treats its project root as a self-contained tree (config/, models/,
artifacts/ live beside the eli/ package; see eli/core/paths.py and
eli/core/portable_paths.py). The launchers for source installs (RUN_ELI.sh,
bin/elix, eli.gui.app:main) all pin ELI_PROJECT_ROOT + the data/config/models
dirs before the app boots. This hook does the same job for frozen bundles:

* Windows installer / portable unzip: the bundle directory is user-writable,
  so it IS the root — settings, models and artifacts live beside the app,
  exactly like a portable source install. Nothing is copied.

* macOS .app in /Applications and Linux AppImage (read-only squashfs): the
  bundle cannot hold mutable state. First launch materialises a per-user root
  (platform data dir /ELI_v2) and seeds it from the bundle: the eli/ source
  tree (ELI self-inspects its own code), config templates, blueprints and
  manifests. Code/data dirs are re-seeded on version upgrades; user files
  (config/settings.json, artifacts/, models/) are never overwritten.

Explicit ELI_PROJECT_ROOT / ELI_*_DIR environment variables always win —
the hook only fills in what the user has not set.
"""
import os
import shutil
import sys
from pathlib import Path

# Directories/files seeded into a per-user root when the bundle is read-only.
# eli/ and api/ are the source trees (introspection + plugin discovery read
# them from disk); the rest are runtime data the app resolves via PROJECT_ROOT.
_SEED_TREES = ("eli", "api", "config", "blueprints", "docs", "packaging/desktop")
_SEED_FILES = (
    "pyproject.toml",
    "capability_manifest.json",
    "capability_inventory.generated.json",
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
)
# Never clobbered on upgrade re-seed: the user's live settings.
_PRESERVE = ("config",)


def _bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))


def _is_writable(path: Path) -> bool:
    probe = path / ".eli_write_probe"
    try:
        probe.touch()
        probe.unlink()
        return True
    except Exception:
        return False


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
            # Only add files the user does not already have (fresh templates
            # on upgrade must not clobber live settings.json etc.).
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

    bundle = _bundle_dir()
    # macOS: a dragged-in .app is usually user-writable, but writing state
    # inside the bundle breaks the codesign seal (fatal on Apple Silicon) —
    # always use the per-user root there.
    if sys.platform != "darwin" and (bundle / "eli").is_dir() and _is_writable(bundle):
        root = bundle
    else:
        root = _user_root()
        try:
            _seed(bundle, root)
        except Exception as exc:  # pragma: no cover — first-run disk issues
            sys.stderr.write(
                f"[ELI] could not prepare user data root {root}: {exc}\n"
                f"[ELI] set ELI_PROJECT_ROOT to a writable ELI directory and relaunch.\n"
            )
            return

    os.environ["ELI_PROJECT_ROOT"] = str(root)
    os.environ.setdefault("ELI_HOME", str(root))
    os.environ.setdefault("ELI_DATA_DIR", str(root / "artifacts"))
    os.environ.setdefault("ELI_CONFIG_DIR", str(root / "config"))
    os.environ.setdefault("ELI_MODELS_DIR", str(root / "models"))


_pin_frozen_root()
