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

The other direction is checked the same way: every newer Python on the
machine must parse the tree without a warning (an invalid escape has warned
since 3.12 and is meant to become an error), and must still have every
standard-library module ELI imports, or a declared requirement must bring it
back. 3.13 removed audioop, which the microphone path imports; audioop-lts is
declared for it, and the next removal is caught here. The interpreters are
found the way the installer finds them (scripts/eli_env.py).
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", "venv", "build", "dist", ".git", ".claude",
             "node_modules", "__pycache__", "experimental", "training"}
HERE = sys.version_info[:2]
_spec = importlib.util.spec_from_file_location("eli_env_for_syntax", REPO / "scripts" / "eli_env.py")
eli_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eli_env)

# One subprocess per interpreter, parsing every file and reporting all failures at once -- a
# per-file subprocess would take minutes on a tree this size. File names come on stdin: the
# list is longer than a Windows command line.
_PARSE = (
    "import ast, json, sys, warnings\n"
    "bad, warned, mods = [], [], {}\n"
    "for f in sys.stdin.read().splitlines():\n"
    "    try:\n"
    "        src = open(f, encoding='utf-8').read()\n"
    "    except Exception:\n"
    "        continue\n"
    "    with warnings.catch_warnings(record=True) as caught:\n"
    "        warnings.simplefilter('always')\n"
    "        try:\n"
    "            tree = ast.parse(src, filename=f)\n"
    "        except SyntaxError as e:\n"
    "            bad.append('%s:%s: %s' % (f, e.lineno, e.msg))\n"
    "            continue\n"
    "    warned += ['%s:%s: %s' % (f, w.lineno, w.message) for w in caught]\n"
    "    for n in ast.walk(tree):\n"
    "        if isinstance(n, ast.Import):\n"
    "            names = [a.name for a in n.names]\n"
    "        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:\n"
    "            names = [n.module]\n"
    "        else:\n"
    "            continue\n"
    "        for name in names:\n"
    "            mods.setdefault(name.split('.')[0], '%s:%s' % (f, n.lineno))\n"
    "print(json.dumps({'bad': bad, 'warned': warned, 'mods': mods,\n"
    "                  'stdlib': sorted(getattr(sys, 'stdlib_module_names', ()))}))\n"
)


def _repo_python_files():
    for p in REPO.rglob("*.py"):
        if SKIP_DIRS & set(p.relative_to(REPO).parts):
            continue
        yield p


@pytest.fixture(scope="module")
def interpreters():
    """Every Python on this machine ELI could be installed with, one per version."""
    found = {}
    for path in eli_env._candidates():
        version = eli_env._version_of(path)
        if version and version >= eli_env.MINIMUM and version not in found:
            found[version] = path
    return found


def _parse_with(interp: str) -> dict:
    files = "\n".join(str(p) for p in _repo_python_files())
    assert files, "found no Python files to check"
    cp = subprocess.run([interp, "-c", _PARSE], input=files, capture_output=True, text=True, timeout=300)
    assert cp.returncode == 0, cp.stderr[-2000:]
    return json.loads(cp.stdout)


def test_pyproject_declares_a_minimum():
    declared = eli_env.declared_minimum(str(REPO))
    assert declared is not None, "pyproject.toml no longer declares requires-python"
    assert declared >= (3, 8)


def test_the_versions_eli_lists_start_at_its_floor_without_gaps():
    """The classifiers and requires-python are two statements of one thing; the release packages
    bundle wheels for every version listed (eli_env.py versions), so a gap is a Python left out."""
    listed = eli_env.declared_versions(str(REPO))
    assert listed and listed[0] == eli_env.declared_minimum(str(REPO))
    assert listed == [(listed[0][0], m) for m in range(listed[0][1], listed[-1][1] + 1)]
    for script in ("build_packages.sh", "scripts/package_desktop_app.sh"):
        text = (REPO / script).read_text(encoding="utf-8")
        assert "for _pv in 3" not in text and "eli_env.py\" versions" in text, script


def test_every_module_parses_on_the_oldest_supported_python(interpreters):
    minimum = eli_env.MINIMUM
    older = sorted(v for v in interpreters if v < HERE)
    if not older:
        pytest.skip(
            f"no interpreter older than {HERE[0]}.{HERE[1]} and >= {minimum[0]}.{minimum[1]} "
            f"on this machine; the CI matrix is the only check on the requires-python claim here"
        )
    interp = interpreters[older[0]]
    offenders = _parse_with(interp)["bad"]
    assert not offenders, (
        f"{len(offenders)} file(s) use syntax newer than "
        f"{minimum[0]}.{minimum[1]} (checked with {interp}):\n  "
        + "\n  ".join(offenders[:15])
    )


def test_every_newer_python_parses_the_tree_and_has_what_it_imports(interpreters):
    newer = sorted(v for v in interpreters if v > HERE)
    if not newer:
        pytest.skip(f"no Python newer than {HERE[0]}.{HERE[1]} on this machine; "
                    f"the CI leg on the newest release is the check here")
    Requirement = pytest.importorskip("packaging.requirements").Requirement
    declared = [Requirement(line) for line in eli_env.requirement_lines(str(REPO / "requirements-full.txt"))]
    ours = set(sys.stdlib_module_names)
    problems = []
    for version in newer:
        got = _parse_with(interpreters[version])
        tag = "%d.%d" % version
        env = {"python_version": tag, "python_full_version": tag + ".0"}
        brought = {eli_env._normal(r.name) for r in declared if r.marker is None or r.marker.evaluate(env)}
        problems += [f"{tag} {line}" for line in got["bad"] + got["warned"]]
        problems += [f"{tag} has no {module} (imported at {where}) and no declared requirement brings it back"
                     for module, where in sorted(got["mods"].items())
                     if module in ours and module not in got["stdlib"]
                     and not brought & {module + "-lts", "standard-" + module}]
    assert not problems, "\n  ".join([f"{len(problems)} problem(s) on newer Pythons:"] + problems[:20])
