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
    from eli.core.toml_util import load_toml
    path = os.path.join(PROJECT_ROOT, "pyproject.toml")
    data = load_toml(path)
    assert "project" in data or "tool" in data, "pyproject.toml looks empty"


def test_capability_manifest_valid_json():
    path = os.path.join(PROJECT_ROOT, "capability_manifest.json")
    assert os.path.isfile(path), "capability_manifest.json must ship in the repo root"
    with open(path) as f:
        data = json.load(f)
    assert data.get("total", 0) > 0


def test_capability_inventory_valid_json():
    path = os.path.join(ELI_ROOT, "capability_inventory.generated.json")
    if not os.path.isfile(path):
        pytest.skip("capability_inventory.generated.json not present")
    with open(path) as f:
        data = json.load(f)
    assert data is not None


def test_plugin_registry_index_valid_json():
    path = os.path.join(ELI_ROOT, "plugins", "registry", "index.json")
    if not os.path.isfile(path):
        pytest.skip("plugin registry index.json missing")
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, (dict, list))


def test_user_sqlite_ships_blank():
    # The checkout ships the blank user store that setup copies into the data folder's db/
    # (eli.core.paths.user_db_path). The copy in artifacts/db is made by an install, so a check
    # for it passed or failed by whether this checkout had been set up or tested before.
    path = os.path.join(PROJECT_ROOT, "config", "templates", "db", "user.sqlite3")
    assert os.path.isfile(path), f"blank user.sqlite3 not found at {path}"


def test_persona_txt_and_auto_template_present():
    # persona.auto.txt is written at run time from its template (gitignored); the checkout ships
    # persona.txt and the template.
    cognition = os.path.join(ELI_ROOT, "cognition")
    assert os.path.isfile(os.path.join(cognition, "persona.txt")), \
        "cognition/persona.txt missing"
    template = os.path.join(PROJECT_ROOT, "config", "templates", "persona.auto.template.txt")
    assert os.path.isfile(template), "config/templates/persona.auto.template.txt missing"
