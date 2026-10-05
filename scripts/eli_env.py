#!/usr/bin/env python3
"""ELI's Python environment: which interpreter to build it with, whether it still works,
and how to mend it.

Standard library only, and written for any Python 3.8+, because it has to run exactly when
the environment it looks after cannot: it is started by whatever Python the launcher or the
installer can find.

    eli_env.py pick                 print the interpreter a new install should use
    eli_env.py status [ROOT]        exit 0 when ROOT/.venv is usable, 3 when it is not
    eli_env.py repair [ROOT]        mend ROOT/.venv if that can be done in place, else say how

Why this exists: a virtual environment is tied to the interpreter it was made with. When an
operating-system upgrade replaces that interpreter (Ubuntu 24.04 -> 26.04 swaps 3.12 for
3.14), the environment's own `python` still starts, as the new version, and cannot see one
package: every launch died with "No module named ...". The same happens on Windows and
macOS when the Python an environment was built from is removed or upgraded.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from typing import Dict, Iterable, List, Optional, Tuple

MINIMUM = (3, 10)
# Versions the inference engine publishes ready-made packages for come first: on those an
# install takes minutes. A newer Python still works, but builds that one package from source.
PREFERRED = ((3, 12), (3, 11), (3, 10), (3, 13), (3, 14))
WINDOWS = os.name == "nt"


def _version_of(python: str) -> Optional[Tuple[int, int]]:
    """(major, minor) of an interpreter, by asking it. None when it does not run."""
    try:
        out = subprocess.run([python, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    parts = (out.stdout or "").split()
    if out.returncode != 0 or len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1])


def _real_executable(python: str) -> Optional[str]:
    """Where an interpreter really lives. "python3.12" on PATH is often a shortcut (a link, or
    a version manager's shim script); an environment has to point at the interpreter itself."""
    try:
        out = subprocess.run(
            [python, "-c", "import os, sys; print(os.path.realpath(getattr(sys, '_base_executable', None) or sys.executable))"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    path = (out.stdout or "").strip()
    return path if out.returncode == 0 and path and os.path.isfile(path) else None


def _candidates(minor: Optional[Tuple[int, int]] = None) -> List[str]:
    """Places an interpreter may be, most specific first. `minor` narrows to one version."""
    names: List[str] = []
    wanted = [minor] if minor else list(PREFERRED)
    for major, mnr in wanted:
        names.append("python%d.%d" % (major, mnr))
    if not minor:
        names += ["python3", "python"]
    found: List[str] = []
    for name in names:
        hit = shutil.which(name)
        if hit:
            found.append(hit)
    home = os.path.expanduser("~")
    for major, mnr in wanted:
        tag, dotted = "%d%d" % (major, mnr), "%d.%d" % (major, mnr)
        patterns = [
            # uv and pyenv keep whole interpreters under the home directory
            os.path.join(home, ".local", "share", "uv", "python", "cpython-%s*" % dotted, "bin", "python%s" % dotted),
            os.path.join(home, ".pyenv", "versions", "%s.*" % dotted, "bin", "python%s" % dotted),
            # Homebrew (Apple silicon, Intel) and python.org on macOS
            "/opt/homebrew/opt/python@%s/bin/python%s" % (dotted, dotted),
            "/usr/local/opt/python@%s/bin/python%s" % (dotted, dotted),
            "/Library/Frameworks/Python.framework/Versions/%s/bin/python%s" % (dotted, dotted),
            "/usr/local/bin/python%s" % dotted,
        ]
        if WINDOWS:
            local = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
            patterns += [
                os.path.join(local, "Programs", "Python", "Python%s" % tag, "python.exe"),
                os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Python%s" % tag, "python.exe"),
                os.path.join(home, "AppData", "Roaming", "uv", "python", "cpython-%s*" % dotted, "python.exe"),
                os.path.join(home, ".pyenv", "pyenv-win", "versions", "%s.*" % dotted, "python.exe"),
            ]
        for pattern in patterns:
            found += sorted(glob.glob(pattern), reverse=True)
    if WINDOWS and shutil.which("py"):
        # the launcher knows every registered install
        for major, mnr in wanted:
            try:
                out = subprocess.run(["py", "-%d.%d" % (major, mnr), "-c", "import sys; print(sys.executable)"],
                                     capture_output=True, text=True, timeout=30)
                if out.returncode == 0 and out.stdout.strip():
                    found.append(out.stdout.strip())
            except (OSError, subprocess.SubprocessError):
                pass
    seen, unique = set(), []
    for path in found:
        key = os.path.normcase(os.path.realpath(path))
        if key not in seen and os.path.isfile(path):
            seen.add(key)
            unique.append(path)
    return unique


def prefer(versions: Iterable[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
    """Of the versions on offer, the one a new install should use. None when none will do."""
    on_offer = {v for v in versions if v and v >= MINIMUM}
    for version in PREFERRED:
        if version in on_offer:
            return version
    return max(on_offer) if on_offer else None


def pick_python() -> Optional[str]:
    """The interpreter a new environment should be built with."""
    by_version: Dict[Tuple[int, int], str] = {}
    for path in _candidates():
        version = _version_of(path)
        if version and version not in by_version:
            by_version[version] = path
    best = prefer(by_version)
    return by_version[best] if best else None


def find_python(minor: Tuple[int, int]) -> Optional[str]:
    """An interpreter of exactly this version, wherever it is installed."""
    for path in _candidates(minor):
        if _version_of(path) == minor:
            return path
    return None


# ── an existing environment ──────────────────────────────────────────────────

def venv_dir(root: str) -> str:
    return os.path.join(os.path.abspath(root), ".venv")


def venv_python(root: str) -> str:
    venv = venv_dir(root)
    return os.path.join(venv, "Scripts", "python.exe") if WINDOWS else os.path.join(venv, "bin", "python")


def _config(root: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        with open(os.path.join(venv_dir(root), "pyvenv.cfg"), encoding="utf-8") as fh:
            for line in fh:
                key, sep, value = line.partition("=")
                if sep:
                    out[key.strip().lower()] = value.strip()
    except OSError:
        pass
    return out


def built_for(root: str) -> Optional[Tuple[int, int]]:
    """The Python version the environment's packages were installed for."""
    venv = venv_dir(root)
    dirs = sorted(glob.glob(os.path.join(venv, "lib", "python3.*", "site-packages")))
    if dirs:
        name = os.path.basename(os.path.dirname(dirs[-1]))          # python3.12
        digits = name.replace("python", "").split(".")
        if len(digits) == 2 and all(d.isdigit() for d in digits):
            return int(digits[0]), int(digits[1])
    version = _config(root).get("version") or _config(root).get("version_info") or ""
    digits = version.split(".")
    if len(digits) >= 2 and digits[0].isdigit() and digits[1].isdigit():
        return int(digits[0]), int(digits[1])
    return None


_SEES_ITS_PACKAGES = (
    "import os, sys\n"
    "ok = any('site-packages' in p and os.path.isdir(p) and os.path.realpath(p).startswith(os.path.realpath(sys.prefix))\n"
    "         for p in sys.path)\n"
    "print(sys.version_info[0], sys.version_info[1], int(ok))\n"
)


def status(root: str) -> Dict[str, object]:
    """Whether ROOT/.venv can run ELI, and in plain words why not."""
    python = venv_python(root)
    made_for = built_for(root)
    if not os.path.isdir(venv_dir(root)):
        return {"ok": False, "why": "missing", "say": "ELI has not been installed here yet.", "built_for": None}
    if not os.path.lexists(python):
        return {"ok": False, "why": "no_interpreter", "built_for": made_for,
                "say": "ELI's environment has no Python in it."}
    try:
        out = subprocess.run([python, "-c", _SEES_ITS_PACKAGES], capture_output=True, text=True, timeout=60)
        parts = (out.stdout or "").split()
    except (OSError, subprocess.SubprocessError):
        out, parts = None, []
    if out is None or out.returncode != 0 or len(parts) != 3:
        return {"ok": False, "why": "dead_interpreter", "built_for": made_for,
                "say": "The Python that ELI's environment was built with is no longer on this computer."}
    running = (int(parts[0]), int(parts[1]))
    if parts[2] != "1" or (made_for and running != made_for):
        was = "%d.%d" % made_for if made_for else "another version"
        return {"ok": False, "why": "version_changed", "built_for": made_for, "running": running,
                "say": "This computer's Python changed from %s to %d.%d, and ELI's environment was built for %s."
                       % (was, running[0], running[1], was)}
    return {"ok": True, "why": "", "say": "ELI's environment is fine.", "built_for": made_for, "running": running}


def relink(root: str, python: str) -> bool:
    """Point the environment at `python`, an interpreter of the version it was built for.
    Nothing is downloaded or reinstalled: the packages are already there."""
    venv = venv_dir(root)
    python = _real_executable(python) or ""
    version = _version_of(python) if python else None
    if not version:
        return False
    cfg_path = os.path.join(venv, "pyvenv.cfg")
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    wrote_home = False
    for i, line in enumerate(lines):
        key = line.partition("=")[0].strip().lower()
        if key == "home":
            lines[i] = "home = %s" % os.path.dirname(python)
            wrote_home = True
        elif key in ("executable", "base-executable"):
            lines[i] = "%s = %s" % (line.partition("=")[0].strip(), python)
    if not wrote_home:
        lines.insert(0, "home = %s" % os.path.dirname(python))
    try:
        with open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        if not WINDOWS:
            # on Windows the environment's python.exe is a small launcher that reads `home`;
            # elsewhere it is a link to the interpreter itself
            bin_dir = os.path.join(venv, "bin")
            os.makedirs(bin_dir, exist_ok=True)
            for name in ("python", "python3", "python%d.%d" % version):
                link = os.path.join(bin_dir, name)
                if os.path.lexists(link):
                    os.remove(link)
                os.symlink(python, link)
    except OSError:
        return False
    return bool(status(root)["ok"])


def repair(root: str) -> Dict[str, object]:
    """Mend ROOT/.venv in place if an interpreter of its own version can be found. When none
    can, say what will rebuild it: that needs the installer and a download, so it is not done
    from here."""
    before = status(root)
    if before["ok"]:
        return dict(before, repaired=False)
    made_for = before.get("built_for")
    if before["why"] != "missing" and made_for:
        python = find_python(made_for)                                # type: ignore[arg-type]
        if python and relink(root, python):
            return dict(status(root), repaired=True,
                        say="ELI's environment was pointed back at Python %d.%d (%s). Nothing was reinstalled."
                            % (made_for[0], made_for[1], python))     # type: ignore[index]
    installer = "install.bat" if WINDOWS else "bash install.sh"
    return dict(before, repaired=False,
                fix="Run  %s  in %s  to rebuild it. Your models, memory and settings are not touched."
                    % (installer, os.path.abspath(root)))


def main(argv: List[str]) -> int:
    command = argv[1] if len(argv) > 1 else "status"
    root = argv[2] if len(argv) > 2 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if command == "pick":
        python = pick_python()
        if not python:
            print("No Python %d.%d or newer was found. Install one from https://www.python.org/downloads/ and run this again."
                  % MINIMUM, file=sys.stderr)
            return 2
        print(python)
        return 0
    if command == "status":
        got = status(root)
        print(got["say"])
        return 0 if got["ok"] else 3
    if command == "repair":
        got = repair(root)
        print("[ELI] %s" % got["say"])
        if got.get("fix"):
            print("[ELI] %s" % got["fix"])
        return 0 if got["ok"] else 4
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
