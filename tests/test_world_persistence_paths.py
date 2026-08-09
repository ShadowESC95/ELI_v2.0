"""Lock on world persistence resolving independently of the working directory.

`storage.py` resolves its directory through `get_paths()` and documents exactly
why: a relative ``Path("artifacts/world")`` "would fail silently when cwd is not
the project root". Three sibling modules never got that fix and still carried

    JOURNAL_PATH  = Path("artifacts/world/journal/eli_world_journal.md")
    LEDGER_PATH   = Path("artifacts/world/ledger/provenance.jsonl")
    SNAPSHOT_DIR  = Path("artifacts/world/snapshots")

so the journal, the provenance ledger and the snapshots landed wherever ELI
happened to be launched from — one place when started from the project
directory, another from ``~`` — and in a packaged build tried to write to
``/artifacts`` and failed. All three are silent: the journal appends nowhere in
particular and nothing reports it.
"""
import os
from pathlib import Path

import pytest

from eli.world.persistence.journal import journal_path
from eli.world.persistence.provenance import ledger_path
from eli.world.persistence.snapshots import snapshot_dir
from eli.world.persistence.storage import world_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOLVERS = {"journal": journal_path, "ledger": ledger_path, "snapshots": snapshot_dir}


@pytest.mark.parametrize("name", sorted(RESOLVERS))
def test_paths_are_absolute(name):
    assert RESOLVERS[name]().is_absolute(), f"{name} path is relative to cwd"


@pytest.mark.parametrize("name", sorted(RESOLVERS))
def test_paths_do_not_move_with_the_working_directory(name, tmp_path, monkeypatch):
    """The actual bug: launching from a different directory relocated the data."""
    before = RESOLVERS[name]()
    monkeypatch.chdir(tmp_path)
    assert RESOLVERS[name]() == before


@pytest.mark.parametrize("name", sorted(RESOLVERS))
def test_paths_sit_under_the_shared_world_dir(name):
    """All world state belongs in one place, not scattered per module."""
    assert str(RESOLVERS[name]()).startswith(str(world_dir()))


def test_no_module_level_relative_artifact_paths_remain():
    """Catch the pattern coming back. Comments describing the old bug are fine;
    an assignment is not."""
    import re
    pkg = REPO_ROOT / "eli" / "world"
    offenders = []
    for py in pkg.rglob("*.py"):
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith(('"', "'")):
                continue
            if re.search(r'=\s*Path\(\s*["\']artifacts', line):
                offenders.append(f"{py.relative_to(REPO_ROOT)}:{i}")
    assert not offenders, f"relative artifact paths reintroduced: {offenders}"


def test_world_dir_survives_a_broken_paths_module(monkeypatch):
    """Persistence must not vanish because get_paths() raised — storage has a
    file-relative fallback, and it has to stay absolute too."""
    import eli.core.paths as paths_mod

    def boom():
        raise RuntimeError("paths unavailable")

    monkeypatch.setattr(paths_mod, "get_paths", boom)
    assert world_dir().is_absolute()
