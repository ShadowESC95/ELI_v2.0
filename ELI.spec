# -*- mode: python ; coding: utf-8 -*-
"""
ELI v2 — PyInstaller build specification (Windows / macOS / Linux).

Build:  pyinstaller --noconfirm ELI.spec
Output: dist/ELI/            (onedir bundle; dist/ELI.app on macOS)

Design notes
------------
* One-dir build. The full dependency stack is multi-GB; a one-file build
  would re-extract it on every launch.
* Version, metadata and the Windows version resource are all derived from
  pyproject.toml — nothing is hardcoded here.
* Data files are taken from `git ls-files` ONLY. The working tree contains
  user-personal files (config/settings.json, config/api_token, certs) and
  ~100 GB of local models that must never ship; the git index is the
  authoritative "safe to redistribute" manifest.
* The eli/ source tree ships as data as well as compiled modules: ELI
  self-inspects its own code (code examiner, truth report, plugin discovery,
  self-upgrade) and resolves its project root by locating that tree.
* GGUF models, Piper voices and diffusion weights are runtime downloads —
  never bundled (size + voice-license review; see
  packaging/runtime_asset_manifest.json).
* Mutable-state routing for frozen installs lives in
  packaging/pyinstaller/rthook_eli_frozen_paths.py.
"""

import os
import subprocess
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

ROOT = Path(SPECPATH).resolve()  # noqa: F821 — SPECPATH is provided by PyInstaller
sys.path.insert(0, str(ROOT))

APP_NAME = "ELI"


def _fail(msg: str) -> None:
    raise SystemExit(f"\n[ELI.spec] BUILD FAILED: {msg}\n")


# ── Version — single source of truth is pyproject.toml ──────────────────────
sys.path.insert(0, str(ROOT / "packaging" / "pyinstaller"))
import gen_version_info  # noqa: E402

APP_VERSION = gen_version_info.project_version(ROOT)
print(f"[ELI.spec] building {APP_NAME} {APP_VERSION}")

# ── Sanity checks (fail early, fail loud) ────────────────────────────────────
if not (ROOT / "eli" / "gui" / "app.py").is_file():
    _fail(f"eli package not found under {ROOT} — run PyInstaller from the repo root.")

ICON_ICO = ROOT / "packaging" / "desktop" / "Eli_Icon.ico"
ICON_PNG = ROOT / "packaging" / "desktop" / "eli-256.png"  # 256px master; Eli_Icon.png is only 175px and renders fuzzy
for icon in (ICON_ICO, ICON_PNG):
    if not icon.is_file():
        _fail(f"application icon missing: {icon}")

ENTRY = ROOT / "packaging" / "pyinstaller" / "eli_entry.py"
RTHOOK = ROOT / "packaging" / "pyinstaller" / "rthook_eli_frozen_paths.py"
for req in (ENTRY, RTHOOK):
    if not req.is_file():
        _fail(f"required build file missing: {req}")


# ── Data files — git index is the redistribution manifest ───────────────────
def _tracked(prefix: str) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", prefix],
            capture_output=True, text=True, check=True, cwd=ROOT,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        _fail(
            "data-file manifest requires `git ls-files` (the working tree holds "
            f"personal files that must not ship). git failed: {exc}"
        )
    return [ROOT / rel for rel in out.split("\0") if rel]


DATA_PREFIXES = [
    "eli",                # source tree — self-inspection + project-root detection
    "api",                # REST server + web chat UI (api.server)
    "config",             # tracked seeds only: settings.example.json, templates/, gpu_profiles.json
    "blueprints",         # capability/actions reference read at runtime
    "docs",               # user docs surfaced from the GUI
    "packaging/desktop",  # app icons (eli/gui/branding.py)
    "pyproject.toml",     # runtime version detection (_eli_app_version)
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
    "models/README.txt",
    "models/MODEL_LICENSES.md",
]

datas: list[tuple[str, str]] = []
for prefix in DATA_PREFIXES:
    files = [f for f in _tracked(prefix) if f.is_file() and f.suffix != ".pyc"]
    if not files:
        _fail(f"no git-tracked files found for required data prefix: {prefix!r}")
    for f in files:
        datas.append((str(f), str(f.parent.relative_to(ROOT)) or "."))

# Generated (untracked) manifests ELI's introspection reads at runtime. Fresh
# checkouts create them with `python tools/bootstrap_claims_artifacts.py`
# (release.yml does this before building); absent files only degrade
# introspection detail, so warn instead of failing.
for name in ("capability_manifest.json", "capability_inventory.generated.json"):
    gen = ROOT / name
    if gen.is_file():
        datas.append((str(gen), "."))
    else:
        print(f"[ELI.spec] WARNING: {name} missing — run tools/bootstrap_claims_artifacts.py to bundle it")

# Piper TTS voices — full voice UX ships in the bundle. The .onnx weights are
# NOT in git (too big); CI downloads them from the project's own
# `local-assets-v2.1` release into tts_piper/piper before building (the same
# voice set previous full tarballs shipped). ELI_REQUIRE_VOICES=1 (set in CI)
# makes a voiceless build a hard failure instead of a silent regression.
_voice_dir = ROOT / "tts_piper" / "piper"
_voice_files = sorted(_voice_dir.glob("*.onnx*")) if _voice_dir.is_dir() else []
if not any(f.suffix == ".onnx" for f in _voice_files):
    if os.environ.get("ELI_REQUIRE_VOICES") == "1":
        _fail("ELI_REQUIRE_VOICES=1 but no .onnx voices in tts_piper/piper — "
              "run: gh release download local-assets-v2.1 --pattern '*.onnx*' --dir tts_piper/piper")
    print("[ELI.spec] WARNING: no Piper voices in tts_piper/piper — bundle will rely on runtime voice download")
for f in _voice_files:
    datas.append((str(f), "tts_piper/piper"))


# ── Hidden imports ───────────────────────────────────────────────────────────
def _optional_collect(package: str, *, data: bool = False, libs: bool = False):
    """Collect an optional dependency if installed; report and skip otherwise."""
    try:
        __import__(package)
    except Exception:
        print(f"[ELI.spec] optional dependency not installed — skipped: {package}")
        return []
    if libs:
        return collect_dynamic_libs(package)
    if data:
        return collect_data_files(package)
    return collect_submodules(package)


hiddenimports = []
# ELI loads its own modules dynamically everywhere (plugin loader via
# pkgutil.iter_modules, kernel pipeline, executor via importlib) — collect all.
hiddenimports += collect_submodules("eli")
hiddenimports += collect_submodules("api")
# numpy 2.x: the standard hook missed numpy._core._exceptions on Linux and
# the frozen app died importing numpy — collect the whole package explicitly.
hiddenimports += collect_submodules("numpy")
# Dynamic-dispatch third-party packages PyInstaller cannot trace statically.
for pkg in ("pyttsx3", "plyer.platforms", "uvicorn"):
    hiddenimports += _optional_collect(pkg)
if sys.platform == "win32":
    hiddenimports += ["pyttsx3.drivers.sapi5", "comtypes.stream"]
elif sys.platform == "darwin":
    hiddenimports += ["pyttsx3.drivers.nsss"]
else:
    hiddenimports += ["pyttsx3.drivers.espeak"]
hiddenimports = [h for h in hiddenimports if h]

# `backports` is a NAMESPACE package PyInstaller cannot trace: jaraco.context
# (pulled in via the setuptools/pkg_resources chain) does
# `from backports import tarfile` on Python < 3.12, and the v2.1.0 AppImage
# shipped without it and crashed at boot (ModuleNotFoundError: backports).
# requirements-build.txt guarantees it is installed in the build venv.
for mod in ("backports", "backports.tarfile"):
    try:
        __import__(mod)
        hiddenimports.append(mod)
    except ImportError:
        if sys.version_info < (3, 12):
            _fail(f"{mod} not installed in the build venv — install requirements-build.txt")

# Native/data payloads of optional runtime deps (each has a hook in
# pyinstaller-hooks-contrib; these are belt-and-braces for hook gaps).
binaries = []
binaries += _optional_collect("llama_cpp", libs=True)

# Windows: ship the MSVC runtime app-locally. CI runners have the VC++
# redistributable installed globally, so the selftest passes there — but a
# clean end-user machine without it cannot load llama.dll/onnxruntime
# ("Could not find module ... or one of its dependencies"). App-local CRT
# deployment is Microsoft-sanctioned; the installer additionally runs
# vc_redist.x64.exe for the UCRT on older Windows 10.
if sys.platform == "win32":
    _sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    for _dll in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
                 "msvcp140_1.dll", "msvcp140_2.dll", "concrt140.dll", "vcomp140.dll"):
        _p = _sys32 / _dll
        if _p.is_file():
            binaries.append((str(_p), "."))
        else:
            print(f"[ELI.spec] WARNING: {_dll} not found in System32 — relying on vc_redist at install time")
for pkg in ("llama_cpp", "faster_whisper", "openwakeword", "piper"):
    datas += _optional_collect(pkg, data=True)

excludes = [
    # PyQt is GPL — the shipped binary must stay PySide6-only (pyproject GUI
    # binding policy). Excluding both prevents qt_compat picking up a stray
    # local PyQt install and tainting the bundle.
    "PyQt5", "PyQt6", "PySide2",
    "tkinter", "IPython", "jupyter", "pytest",
]

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[str(RTHOOK)],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

# Windows version resource — generated from pyproject.toml at build time.
version_rc = None
if sys.platform == "win32":
    version_rc = str(gen_version_info.generate(ROOT / "build" / "version.rc"))

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX corrupts Qt/CUDA DLLs — never enable
    console=False,           # GUI app; use ELI_PROJECT_ROOT + a terminal run for debugging
    icon=str(ICON_ICO if sys.platform == "win32" else ICON_PNG),
    version=version_rc,
)

# Second executable, same code: the phone/web server with a REAL console so
# users can see logs + the phone-connect URL. eli_entry.py dispatches to
# api.server:main when the exe name ends in "server" (or --server is passed).
exe_server = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=f"{APP_NAME}-Server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(ICON_ICO if sys.platform == "win32" else ICON_PNG),
    version=version_rc,
)

coll = COLLECT(
    exe,
    exe_server,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(ICON_PNG),  # PyInstaller converts to .icns via Pillow
        bundle_identifier="com.shadowesc95.eli",
        version=APP_VERSION,
        info_plist={
            "CFBundleName": "ELI",
            "CFBundleDisplayName": "ELI v2.0",
            "CFBundleShortVersionString": APP_VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "NSMicrophoneUsageDescription":
                "ELI uses the microphone for voice conversations and wake-word listening.",
            "NSCameraUsageDescription":
                "ELI uses the camera only when you enable vision features.",
            "NSAppleEventsUsageDescription":
                "ELI automates apps you ask it to control.",
        },
    )
