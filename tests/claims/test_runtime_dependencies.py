"""CLAIM: every package ELI imports when it runs reaches every user, whichever way they install it.

SpeechRecognition was in requirements.txt and the lock, but pyproject.toml carried it only in the
optional `asr` extra, and the voice output, the window, the server and the rest each in an extra of
their own. What a user got depended on how they installed: a plain `pip install` had no voice input or
output, no window and no server. pyproject's dependencies now carry everything
ELI needs to run its features; only what is built for, or chosen by, the machine's GPU stays optional.

These tests read every import in eli/ and api/ (lazy ones inside functions and importlib's string
imports too) and hold each third-party one to every place that installs packages: pyproject.toml,
each requirements file on the systems it serves, the lock, and the workflows that build a release and
test it. A new import that no install route declares fails here, not on a user's machine.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

import pytest

from eli.core.toml_util import loads_toml

from . import _helpers as H

Requirement = pytest.importorskip("packaging.requirements").Requirement

REPO = H.REPO
_spec = importlib.util.spec_from_file_location("eli_env_for_claims", REPO / "scripts" / "eli_env.py")
eli_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eli_env)

# Import names whose distribution is called something else (spelling alone, `_` for `-` or the case,
# is not listed: names are compared in PEP 503 form).
DISTRIBUTION = {
    "PIL": "pillow",
    "cv2": "opencv-python",
    "docx": "python-docx",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "paho": "paho-mqtt",
    "speech_recognition": "speechrecognition",
    "faiss": "faiss-cpu",
    "llama_cpp": "llama-cpp-python",
    "piper": "piper-tts",
    "win32com": "pywin32",
    "TTS": "coqui-tts",
    "yara": "yara-python",
}

# Imported, never declared anywhere, and why.
NOT_DECLARED = {
    "PyQt5": "a GPL binding; ELI ships PySide6, and eli/gui/qt_compat.py uses PyQt only where the user has it",
    "PyQt6": "a GPL binding; ELI ships PySide6, and eli/gui/qt_compat.py uses PyQt only where the user has it",
    "gi": "PyGObject comes with the Linux desktop (python3-gi); pip cannot build it without the system's "
          "own build files, and a packaged ELI asks the system's Python for it",
}

# Built for, or chosen by, the machine's GPU. The installers fetch each by a step of their own: the
# engine is built for CUDA, Metal, ROCm, Vulkan or the CPU, and PyTorch comes from the index for the GPU
# found; the rest run on PyTorch. Only these may wait in an optional extra.
GPU_BOUND = frozenset({"llama-cpp-python", "torch", "torchaudio", "torchcodec", "diffusers", "transformers",
                       "peft", "datasets", "bitsandbytes", "coqui-tts"})

# What each requirements file is installed on (install.sh, install.ps1 and their fallbacks): the lock on
# Linux and Windows, the ranges when the lock cannot be met there, requirements-macos.txt on a Mac.
ROUTES = {
    "requirements.lock.txt": ("linux", "win32"),
    "requirements.txt": ("linux",),
    "requirements-full.txt": ("linux",),
    "requirements-windows.txt": ("win32",),
    "requirements-macos.txt": ("darwin",),
}
_SYSTEM = {"linux": ("Linux", "posix"), "win32": ("Windows", "nt"), "darwin": ("Darwin", "posix")}

_IMPORT_CALLS = {"import_module", "__import__", "find_spec"}
_NOT_SOURCE = {"artifacts", "models", "build", "dist", "node_modules", "__pycache__", "tests"}


def _normal(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@lru_cache(maxsize=1)
def _own_modules() -> frozenset:
    """Top-level names this repository provides itself (eli, api, the GPU pack module, the gaze kit): the
    modules and packages in a folder that is not itself a package. A module inside a package (a
    eli/.../web package) is not importable by its bare name and does not hide a library of that name."""
    own = {"eli", "api", "__future__"}
    for here, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _NOT_SOURCE]
        if "__init__.py" in files:
            dirs[:] = []
            continue
        own.update(f[:-3] for f in files if f.endswith(".py"))
        own.update(d for d in dirs if (Path(here) / d / "__init__.py").is_file())
    return frozenset(own)


def _imports_in(tree: ast.AST) -> list:
    """(top-level module, line) of every absolute import under ``tree``, string imports included."""
    found = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            found += [(a.name.split(".")[0], n.lineno) for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            found.append((n.module.split(".")[0], n.lineno))
        elif isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant) \
                and isinstance(n.args[0].value, str):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in _IMPORT_CALLS:
                found.append((n.args[0].value.split(".")[0], n.lineno))
    return found


@lru_cache(maxsize=1)
def _scan() -> tuple:
    """({module: [where]} ELI imports, {module: [where]} it imports only as a fallback for another).

    A fallback is an import in the `except` branch of a `try` whose body imports a third-party package:
    the old name of a renamed package (duckduckgo_search for ddgs, PyPDF2 for pypdf), tried only when
    the declared one is missing."""
    skip = set(sys.stdlib_module_names) | _own_modules()
    used: dict = {}
    fallback: dict = {}
    for root in ("eli", "api"):
        for path in sorted((REPO / root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            rel = H.rel(path)
            spare = set()
            for t in ast.walk(tree):
                if isinstance(t, ast.Try) and any(m not in skip for s in t.body for m, _ in _imports_in(s)):
                    spare |= {(m, line) for h in t.handlers for s in h.body for m, line in _imports_in(s)}
            for module, line in _imports_in(tree):
                if module in skip:
                    continue
                book = fallback if (module, line) in spare else used
                book.setdefault(module, []).append(f"{rel}:{line}")
    for module in list(fallback):
        if module in used:
            fallback.pop(module)
    return used, fallback


def _runtime() -> dict:
    """{distribution: [where]} for every third-party import ELI makes when it runs."""
    used, _ = _scan()
    out: dict = {}
    for module, where in used.items():
        if module in NOT_DECLARED:
            continue
        out.setdefault(_normal(DISTRIBUTION.get(module, module)), []).extend(where)
    return out


@lru_cache(maxsize=1)
def _project() -> dict:
    return loads_toml((REPO / "pyproject.toml").read_bytes())["project"]


def _base() -> list:
    return [Requirement(text) for text in _project()["dependencies"]]


def _extras() -> dict:
    return {name: [Requirement(text) for text in texts]
            for name, texts in _project()["optional-dependencies"].items()}


def _environments(system: str):
    platform_system, os_name = _SYSTEM[system]
    for major, minor in eli_env.declared_versions(str(REPO)):
        version = f"{major}.{minor}"
        yield version, {"sys_platform": system, "platform_system": platform_system, "os_name": os_name,
                        "python_version": version, "python_full_version": version + ".0", "extra": ""}


def _applies(req, env) -> bool:
    return req.marker is None or req.marker.evaluate(env)


def _where(dist: str) -> str:
    places = _runtime()[dist]
    return ", ".join(places[:3]) + (f" (+{len(places) - 3})" if len(places) > 3 else "")


def test_eli_imports_third_party_packages_at_all():
    """The scan itself works: it finds the voice input this file was written for, lazy imports included."""
    runtime = _runtime()
    assert {"speechrecognition", "pyaudio", "pyside6", "fastapi"} <= set(runtime), sorted(runtime)


def test_every_runtime_import_is_declared_somewhere():
    project = {_normal(r.name) for r in _base()} | {_normal(r.name) for reqs in _extras().values() for r in reqs}
    missing = sorted(d for d in _runtime() if d not in project)
    assert not missing, "imported by ELI, declared in pyproject.toml nowhere:\n  " + \
        "\n  ".join(f"{d} ({_where(d)})" for d in missing)


def test_a_plain_install_brings_everything_but_what_the_gpu_decides():
    """`pip install` of the project, which every installer, build and workflow starts from."""
    base = {_normal(r.name) for r in _base()}
    optional = sorted(d for d in _runtime() if d not in base and d not in GPU_BOUND)
    assert not optional, "only in an optional extra, so a plain install has no feature that uses it:\n  " + \
        "\n  ".join(f"{d} ({_where(d)})" for d in optional)


def test_an_optional_extra_holds_only_what_the_gpu_decides():
    """An extra for what installs the same way everywhere is how voice input came to be left out."""
    wrong = sorted(name for name, reqs in _extras().items() if name not in ("test", "full")
                   and not {_normal(r.name) for r in reqs} & GPU_BOUND)
    assert not wrong, f"extras with nothing the GPU decides; their packages belong in dependencies: {wrong}"


@pytest.mark.parametrize("name,system", [(n, s) for n, systems in ROUTES.items() for s in systems])
def test_each_requirements_file_brings_every_dependency_on_its_system(name, system):
    """install.sh and install.ps1 install pyproject's set and then the file for the system; where the lock
    cannot be met they fall back to the ranges, one package at a time. Each must bring the whole set."""
    have = [Requirement(line) for line in eli_env.requirement_lines(str(REPO / name))]
    gaps = []
    for version, env in _environments(system):
        brought = {_normal(r.name) for r in have if _applies(r, env)}
        gaps += [f"{version}: {_normal(r.name)}" for r in _base()
                 if _applies(r, env) and _normal(r.name) not in brought]
    assert not gaps, f"{name} on {system} leaves out what pyproject.toml's dependencies hold:\n  " + "\n  ".join(gaps)


def _workflow(name: str) -> str:
    return (REPO / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _extras_named(text: str, var: str) -> set:
    return {e for line in re.findall(rf"^\s*{var}:\s*\"([^\"]*)\"", text, re.M) for e in line.split()}


def test_the_release_builds_carry_what_a_full_install_has():
    release = _workflow("release.yml")
    bundled = _extras_named(release, "REQUIRED_EXTRAS") | _extras_named(release, "OPTIONAL_EXTRAS")
    full = set(_project()["optional-dependencies"]["full"][0].split("[", 1)[1].rstrip("]").split(","))
    assert full <= bundled, f"a full install has {sorted(full - bundled)}, the release builds do not"


def test_the_release_tests_run_on_what_the_linux_build_bundles():
    """The release's test job and its Linux build install their packages with one script, so the tests
    run against exactly what is bundled; and the cross-platform check installs what a plain install
    brings, so each system and Python it runs on proves that set installs."""
    release = _workflow("release.yml")
    for job in ("\n  build-linux:", "\n  tests:"):
        body = release.split(job, 1)[1].split("\n  build-", 1)[0].split("\n  release:", 1)[0]
        assert "bash packaging/ci_linux_deps.sh" in body, f"{job.strip()} does not install with the build's script"
    script = (REPO / "packaging" / "ci_linux_deps.sh").read_text(encoding="utf-8")
    assert "$REQUIRED_EXTRAS" in script and "$OPTIONAL_EXTRAS" in script
    smoke = [line.strip() for line in _workflow("cross-platform-smoke.yml").splitlines()
             if "pip install -e" in line and not line.strip().startswith("#")]
    assert smoke and all(line in ("pip install -e .", 'pip install -e "."') for line in smoke), smoke


# `.[x]`, `eli-v2.0[x]`, `<wheel>.whl[x]`, `$ROOT[x]`, `${DIR}[x]`: the project with an extra
_ASKED = re.compile(r"(?:\.|eli-v2\.0|\.whl|(?:ROOT|DIR)\}?)\[([a-z][a-z0-9_-]*(?:,[a-z0-9_-]+)*)\]")


def test_every_extra_a_workflow_or_installer_asks_for_exists():
    """pip warns about an extra the project does not have and goes on without it."""
    have = set(_project()["optional-dependencies"])
    places = list((REPO / ".github" / "workflows").glob("*.yml"))
    places += [REPO / n for n in ("install.sh", "install.ps1", "install.bat", "build_packages.sh", "run_tests.sh")]
    places += list((REPO / "scripts").glob("*.sh")) + list((REPO / "scripts").glob("*.ps1"))
    places += list((REPO / "packaging").rglob("*.sh")) + list((REPO / "packaging").rglob("*.ps1"))
    wrong = []
    for path in places:
        if not path.is_file():
            continue
        for match in _ASKED.finditer(path.read_text(encoding="utf-8", errors="replace")):
            wrong += [f"{H.rel(path)}: {e}" for e in match.group(1).split(",") if e not in have]
    assert not wrong, "asks for an extra pyproject.toml does not define:\n  " + "\n  ".join(wrong)


def test_every_import_name_maps_to_the_distribution_installed_for_it():
    """The table above, checked against the packages this environment holds."""
    from importlib import metadata
    owners = metadata.packages_distributions()
    wrong = [f"{module}: {DISTRIBUTION[module]}, installed as {owners[module]}"
             for module in DISTRIBUTION if module in owners
             and _normal(DISTRIBUTION[module]) not in {_normal(d) for d in owners[module]}]
    assert not wrong, wrong


def test_what_is_left_undeclared_is_still_imported():
    used, fallback = _scan()
    stale = sorted(m for m in NOT_DECLARED if m not in used and m not in fallback)
    assert not stale, f"no longer imported; take them out of NOT_DECLARED: {stale}"
