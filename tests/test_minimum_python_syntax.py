"""Every shipped module must parse on the OLDEST Python this project supports.

Live failure this locks: `tests/test_install_script.py` used a backslash
inside an f-string expression --

    f"{raw.count(b'\\n')} LF vs {raw.count(b'\\r\\n')} CRLF"

-- which PEP 701 legalised in Python 3.12 and which is a hard SyntaxError on
3.10 and 3.11. The development venv is 3.12, so it passed locally and on the
py3.12 CI legs, then failed collection on all three py3.10 runners at once
(ubuntu, macOS and Windows), turning a one-line typo into a red main branch.

pyproject declares `requires-python = ">=3.10"`. That claim is only worth
something if it is checked, and the running interpreter cannot check it --
newer syntax parses fine on the newer parser by definition. So when an older
interpreter is present, use it; when it is not, say so out loud rather than
passing silently, because CI is then the only thing standing behind the claim.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", "venv", "build", "dist", ".git", ".claude",
             "node_modules", "__pycache__", "experimental", "training"}


def _declared_minimum() -> tuple:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'requires-python\s*=\s*["\']>=\s*(\d+)\.(\d+)', text)
    assert m, "pyproject.toml no longer declares requires-python"
    return int(m.group(1)), int(m.group(2))


def _oldest_available_interpreter(minimum: tuple):
    """The oldest interpreter on this machine at or above the declared floor
    and below the one running the tests, or None."""
    running = sys.version_info[:2]
    candidates = []
    for minor in range(minimum[1], running[1]):
        name = f"python{minimum[0]}.{minor}"
        found = shutil.which(name) or shutil.which(str(Path.home() / ".local/bin" / name))
        local = Path.home() / ".local" / "bin" / name
        if not found and local.exists():
            found = str(local)
        if found:
            candidates.append((minor, found))
    return candidates[0][1] if candidates else None


def _repo_python_files():
    for p in REPO.rglob("*.py"):
        if SKIP_DIRS & set(p.relative_to(REPO).parts):
            continue
        yield p


def test_pyproject_declares_a_minimum():
    assert _declared_minimum() >= (3, 8)


def test_every_module_parses_on_the_oldest_supported_python():
    minimum = _declared_minimum()
    interp = _oldest_available_interpreter(minimum)
    if not interp:
        pytest.skip(
            f"no interpreter older than {sys.version_info.major}.{sys.version_info.minor} "
            f"and >= {minimum[0]}.{minimum[1]} on this machine; the CI matrix is the "
            f"only check on the requires-python claim here"
        )

    files = [str(p) for p in _repo_python_files()]
    assert files, "found no Python files to check"

    # One subprocess, parsing every file, reporting all failures at once --
    # a per-file subprocess would take minutes on a tree this size.
    prog = (
        "import ast,sys\n"
        "bad=[]\n"
        "for f in sys.argv[1:]:\n"
        "    try:\n"
        "        ast.parse(open(f,encoding='utf-8').read(), filename=f)\n"
        "    except SyntaxError as e:\n"
        "        bad.append(f'{f}:{e.lineno}: {e.msg}')\n"
        "    except Exception:\n"
        "        pass\n"
        "print('\\n'.join(bad))\n"
    )
    cp = subprocess.run([interp, "-c", prog, *files],
                        capture_output=True, text=True, timeout=300)
    offenders = [ln for ln in (cp.stdout or "").splitlines() if ln.strip()]
    assert not offenders, (
        f"{len(offenders)} file(s) use syntax newer than "
        f"{minimum[0]}.{minimum[1]} (checked with {interp}):\n  "
        + "\n  ".join(offenders[:15])
    )
