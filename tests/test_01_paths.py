import pytest
from pathlib import Path
from eli.core.paths import get_paths, project_root, artifacts_dir, config_dir

def test_project_root():
    root = project_root()
    assert (root / "eli").exists()
    assert (root / "README.md").exists()

def test_artifacts_dir():
    art = artifacts_dir()
    assert art.parent == project_root()
    assert art.name == "artifacts"

def test_config_dir():
    cfg = config_dir()
    assert cfg.exists() or cfg.parent.exists()

def test_get_paths():
    paths = get_paths()
    assert paths.project_root == project_root()
    assert paths.artifacts_dir == artifacts_dir()
    assert paths.user_db.suffix == ".sqlite3"
