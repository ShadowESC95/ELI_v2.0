"""The constraints the release build installs under: requirements.lock.txt, less any pin that
requirements-build.txt does not allow.

The release build used to install ELI's packages unconstrained (only llama-cpp-python was held),
so a bundle took the newest of everything. PyAV 18 refuses an argument faster-whisper 1.2.1
passes, and every transcription in the 2.5.11 packaged app failed. The installers already keep
to the lock; the build now does too, except where its own tooling needs otherwise (setuptools is
held below 81 for PyInstaller's pkg_resources hook, and the lock has 81.0.0).

usage: python packaging/lock_constraints.py <output file>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _key(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _specifier(text: str):
    try:
        from packaging.specifiers import SpecifierSet
    except ImportError:
        from pip._vendor.packaging.specifiers import SpecifierSet
    return SpecifierSet(text)


def build_requirements(path: Path) -> dict:
    """{name: specifier text} from requirements-build.txt (markers and comments left out)."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].split(";", 1)[0].strip()
        m = _NAME.match(line)
        if m:
            out[_key(m.group(1))] = line[m.end():].strip()
    return out


def constraints(lock: Path, build: Path) -> list:
    wanted = build_requirements(build)
    kept, dropped = [], []
    for line in lock.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        m = _NAME.match(text)
        if not text or text.startswith("#") or not m:
            continue
        name = _key(m.group(1))
        pin = re.search(r"==\s*([^\s;]+)", text)
        spec = wanted.get(name)
        if spec and pin and pin.group(1) not in _specifier(spec):
            dropped.append(f"{m.group(1)}=={pin.group(1)} (the build needs {spec})")
            continue
        kept.append(text)
    for d in dropped:
        print(f"lock pin left to the build: {d}", file=sys.stderr)
    return kept


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(constraints(ROOT / "requirements.lock.txt", ROOT / "requirements-build.txt")) + "\n",
                   encoding="utf-8")
