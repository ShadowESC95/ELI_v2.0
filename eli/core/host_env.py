"""The environment a program ELI starts should see: the machine's own, not the bundle's.

A frozen build (AppImage, PyInstaller) points LD_LIBRARY_PATH at its own libraries, and sets
QT_PLUGIN_PATH, SSL_CERT_FILE and friends to paths inside itself. A system program started with
that environment loads the bundle's older libraries by soname. Live in 2.5.6 on Ubuntu 26.04:
dbus-send died on the bundle's libdbus ("LIBDBUS_PRIVATE_1.16.2 not found"), so every MPRIS
call to Spotify failed; /usr/bin/yt-dlp died on the bundle's libcrypto; Spotify launched by ELI
exited at once while ELI reported "Opened app: Spotify".

install() wraps subprocess.Popen once, at startup: a program from outside the bundle gets
host_env(); ELI's own executable and anything else inside the bundle keep the environment as it
is (they need it). Programs started by Qt itself (QDesktopServices) are not covered.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Mapping, Optional

# Plain logging: this loads before anything else in a frozen build.
log = logging.getLogger(__name__)

# Variables that hold a list of directories: only the bundle's entries are taken out.
_PATH_LISTS = frozenset({
    "PATH", "LD_LIBRARY_PATH", "LD_PRELOAD", "XDG_DATA_DIRS", "XDG_CONFIG_DIRS", "PYTHONPATH",
    "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "GST_PLUGIN_PATH", "GST_PLUGIN_SYSTEM_PATH",
    "GIO_EXTRA_MODULES", "GTK_PATH", "PERLLIB", "PERL5LIB",
})


def _norm(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path)).rstrip(os.sep)


def _candidates() -> List[str]:
    found = [getattr(sys, "_MEIPASS", None), os.environ.get("APPDIR")]
    if getattr(sys, "frozen", False):
        found.append(os.path.dirname(sys.executable))
    return [str(c).rstrip(os.sep) for c in found if c and str(c).rstrip(os.sep)]


def bundle_roots() -> List[str]:
    """Directories that belong to the running bundle; empty when ELI runs from source."""
    roots: List[str] = []
    for c in _candidates():
        n = _norm(c)
        if n and n != os.sep and n not in roots:
            roots.append(n)
    return roots


def _inside(path: str, roots: List[str]) -> bool:
    if not path or not os.path.isabs(os.path.expanduser(path)):
        return False
    p = _norm(path)
    return any(p == r or p.startswith(r + os.sep) for r in roots)


def host_env(base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """`base` (default os.environ) as the machine's programs expect it: LD_LIBRARY_PATH as it was
    before the bundle started, no entries pointing into the bundle, no PyInstaller internals."""
    env = dict(os.environ if base is None else base)
    roots = bundle_roots()
    if not roots:
        return env
    # The bundle as given and as resolved: on macOS a temp dir under /var is /private/var resolved.
    spellings = set(roots) | {c for c in _candidates() if c != os.sep}
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    for key in list(env):
        if key.startswith("_PYI_") or key in ("_MEIPASS2", "APPDIR", "APPIMAGE_SILENT_INSTALL"):
            env.pop(key, None)
            continue
        value = env[key]
        if not any(r in value for r in spellings):
            continue
        if key in _PATH_LISTS or os.pathsep in value:
            parts = value.split(os.pathsep)
            kept = [p for p in parts if not _inside(p, roots)]
            if len(kept) == len(parts):
                continue
            if any(kept):
                env[key] = os.pathsep.join(kept)
            else:
                env.pop(key, None)
        elif _inside(value, roots):
            env.pop(key, None)   # one path into the bundle: QT_PLUGIN_PATH, SSL_CERT_FILE, ...
    if not env.get("LD_LIBRARY_PATH"):
        env.pop("LD_LIBRARY_PATH", None)
    return env


def _program(args, kwargs) -> str:
    """The file that will run, as far as it can be told without running it."""
    if kwargs.get("shell"):
        return "/bin/sh"
    exe = kwargs.get("executable")
    if not exe:
        if isinstance(args, (str, bytes, os.PathLike)):
            exe = args
        elif args:
            exe = args[0]
    exe = os.fsdecode(exe) if exe else ""
    if exe and os.sep not in exe:
        path = (kwargs.get("env") or os.environ).get("PATH")
        exe = shutil.which(exe, path=path) or exe
    return exe


def _for_bundle(exe: str) -> bool:
    roots = bundle_roots()
    if not roots:
        return True
    if exe and _norm(exe) == _norm(sys.executable):
        return True
    return _inside(exe, roots)


_installed = False


def install() -> None:
    """Give every program from outside the bundle the machine's environment. A no-op from source."""
    global _installed
    if _installed or not bundle_roots():
        return
    original = subprocess.Popen.__init__

    def __init__(self, args, *pargs, **kwargs):
        try:
            if len(pargs) < 10 and not _for_bundle(_program(args, kwargs)):   # env is the 11th
                kwargs["env"] = host_env(kwargs.get("env"))
        except Exception:
            log.debug("suppressed exception", exc_info=True)
        original(self, args, *pargs, **kwargs)

    subprocess.Popen.__init__ = __init__
    _installed = True
