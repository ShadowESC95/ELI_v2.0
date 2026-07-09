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

# Directories/files seeded into the per-user root. eli/ and api/ are the
# source trees (introspection + plugin discovery read them from disk); the
# rest are runtime data the app resolves via PROJECT_ROOT.
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
# Merge-only trees: add missing files, never clobber what the user has
# (config/ holds live settings.json, tokens, certs).
_PRESERVE = ("config",)


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
