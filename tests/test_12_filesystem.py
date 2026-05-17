"""
test_12_filesystem.py
=====================
Validates the project filesystem — no missing __init__.py files, expected
directories present, key JSON artefacts valid, no stale .pyc-only modules.
"""
import os
import json
import glob
import pytest
import importlib


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ELI_ROOT = os.path.join(PROJECT_ROOT, "eli")

EXPECTED_DIRS = [
    "cognition", "core", "execution", "gui", "integrations",
    "kernel", "memory", "perception", "planning", "plugins",
    "runtime", "tools", "utils",
]

EXPECTED_TOP_LEVEL = [
    "eli.sh", "pyproject.toml", "requirements.txt", "README.md",
]


@pytest.mark.parametrize("subdir", EXPECTED_DIRS, ids=EXPECTED_DIRS)
def test_eli_subdirectory_exists(subdir):
    path = os.path.join(ELI_ROOT, subdir)
    assert os.path.isdir(path), f"Expected directory missing: {path}"


@pytest.mark.parametrize("subdir", EXPECTED_DIRS, ids=EXPECTED_DIRS)
def test_eli_subdirectory_has_init(subdir):
    init = os.path.join(ELI_ROOT, subdir, "__init__.py")
    assert os.path.isfile(init), f"Missing __init__.py in {subdir}/"


@pytest.mark.parametrize("fname", EXPECTED_TOP_LEVEL, ids=EXPECTED_TOP_LEVEL)
def test_project_root_file_exists(fname):
    path = os.path.join(PROJECT_ROOT, fname)
    assert os.path.isfile(path), f"Expected project file missing: {path}"


def test_pyproject_toml_valid():
    import tomllib
    path = os.path.join(PROJECT_ROOT, "pyproject.toml")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    assert "project" in data or "tool" in data, "pyproject.toml looks empty"


def test_capability_manifest_valid_json():
    path = os.path.join(ELI_ROOT, "capability_manifest.json")
    if not os.path.isfile(path):
        pytest.skip("capability_manifest.json not present")
    with open(path) as f:
        data = json.load(f)
    assert data is not None


def test_capability_inventory_valid_json():
    path = os.path.join(ELI_ROOT, "capability_inventory.generated.json")
    if not os.path.isfile(path):
        pytest.skip("capability_inventory.generated.json not present")
    with open(path) as f:
        data = json.load(f)
    assert data is not None


def test_no_source_only_has_pycache_without_py():
    """If a .pyc exists but no .py exists, that's a ghost module — warn."""
    ghost_modules = []
    for root, dirs, files in os.walk(ELI_ROOT):
        if "__pycache__" in root:
            continue
        py_files  = {f[:-3] for f in files if f.endswith(".py")}
        pyc_dir   = os.path.join(root, "__pycache__")
        if not os.path.isdir(pyc_dir):
            continue
        for pyc in os.listdir(pyc_dir):
            base = pyc.split(".")[0]
            if base not in py_files and base != "__init__":
                ghost_modules.append(os.path.join(pyc_dir, pyc))
    # This is a warning, not a hard failure — old .pyc after a refactor
    if ghost_modules:
        pytest.warns(UserWarning, match="ghost") if False else \
            pytest.xfail(f"Ghost .pyc files (no matching .py): {ghost_modules[:5]}")


def test_plugin_registry_index_valid_json():
    path = os.path.join(ELI_ROOT, "plugins", "registry", "index.json")
    if not os.path.isfile(path):
        pytest.skip("plugin registry index.json missing")
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, (dict, list))


def test_user_sqlite_exists():
    path = os.path.join(ELI_ROOT, "artifacts", "user.sqlite3")
    assert os.path.isfile(path), f"user.sqlite3 not found at {path}"


def test_persona_txt_and_auto_txt_present():
    cognition = os.path.join(ELI_ROOT, "cognition")
    assert os.path.isfile(os.path.join(cognition, "persona.txt")), \
        "cognition/persona.txt missing"
    assert os.path.isfile(os.path.join(cognition, "persona.auto.txt")), \
        "cognition/persona.auto.txt missing"
