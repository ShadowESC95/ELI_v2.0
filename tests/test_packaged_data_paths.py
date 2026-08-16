"""Locks on runtime data being read from where it is actually written.

Live failure at 2.1.97. Asked "who am i?", ELI answered:

    Personal memory summary unavailable: active user DB does not exist at
    /tmp/.mount_ELI_v2bIpcAe/usr/app/_internal/artifacts/db/user.sqlite3

while the proactive daemon in the SAME process was correctly using
~/.local/share/ELI_v2/artifacts/db/user.sqlite3. The module derived its path
from ``Path(__file__).resolve().parents[2]``, which inside an AppImage is the
read-only squashfs mount the code was extracted to — a tree that contains no
artifacts at all.

ce40453 swept three modules for exactly this and the sweep was incomplete; ten
more were still resolving runtime data from the install tree. Three of those
were WRITE paths, which is worse than a stale read: the mount is read-only, so
they could never persist anything.

The distinction the code has to respect: project root is where the CODE lives,
the artifacts dir is where DATA lives. They are the same directory in a source
checkout — which is why this survives local testing — and different ones in
every shipped build.
"""
from pathlib import Path

import pytest

import eli.core.paths as P

PACKAGED = Path("/srv/packaged-user-data/artifacts")


@pytest.fixture
def packaged(monkeypatch):
    """Simulate a build where data lives apart from the code."""
    monkeypatch.setattr(P, "data_dir", lambda: PACKAGED)
    monkeypatch.setattr(P, "project_root", lambda: Path("/ro/mount/usr/app"))
    yield


def _under_packaged(p) -> bool:
    return str(p).startswith(str(PACKAGED))


# ── the module that actually failed ────────────────────────────────────────
def test_personal_memory_surface_uses_the_data_dir(packaged):
    from eli.runtime.personal_memory_surface import _artifacts_dir
    assert _under_packaged(_artifacts_dir())


def test_who_am_i_does_not_point_inside_the_install_tree(packaged):
    """The exact symptom: a /tmp/.mount_* path in a user-facing error."""
    from eli.runtime.personal_memory_surface import _artifacts_dir
    assert ".mount_" not in str(_artifacts_dir())
    assert "_internal" not in str(_artifacts_dir())


# ── the snapshot readers (the 2.1.82 self-report failure class) ────────────
@pytest.mark.parametrize("module,attr", [
    ("eli.runtime.deterministic_grounding_gate", "_artifacts_dir"),
    ("eli.runtime.user_visible_response_surface", "_artifacts_dir"),
])
def test_snapshot_readers_use_the_data_dir(packaged, module, attr):
    import importlib
    mod = importlib.import_module(module)
    assert _under_packaged(getattr(mod, attr)())


# ── the write paths — worst case, the mount is read-only ──────────────────
def test_self_heal_notices_are_writable(packaged):
    from eli.runtime.self_improvement import _self_heal_notices_path
    assert _under_packaged(_self_heal_notices_path())


def test_tool_result_store_is_writable(packaged, monkeypatch, tmp_path):
    monkeypatch.setattr(P, "data_dir", lambda: tmp_path / "artifacts")
    from eli.runtime.tool_result_store import tool_result_store_path
    p = tool_result_store_path()
    assert str(p).startswith(str(tmp_path)), "would write into the install tree"
    assert p.parent.exists(), "parent not created"


def test_grounded_remediation_is_writable(packaged, monkeypatch, tmp_path):
    monkeypatch.setattr(P, "data_dir", lambda: tmp_path / "artifacts")
    from eli.runtime.grounded_remediation import _pending_file
    assert str(_pending_file()).startswith(str(tmp_path))


# ── the pattern must not come back ─────────────────────────────────────────
def test_no_module_reads_runtime_data_from_its_own_location():
    """A module may resolve its own file location — for source paths, or as a
    fallback after the canonical resolver. What it must not do is build a
    runtime DATA path from it with no canonical resolver anywhere in the file."""
    import re

    repo = Path(__file__).resolve().parents[1]
    canonical = re.compile(r"get_paths|data_dir|user_db_path|memory_db_path|artifacts_dir|ARTIFACTS_DIR")
    file_rel = re.compile(r"Path\(__file__\)\.resolve\(\)\.parents\[\d\]")
    data_path = re.compile(r'/\s*["\']artifacts["\']')

    offenders = []
    for py in (repo / "eli").rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if not file_rel.search(text) or not data_path.search(text):
            continue
        if canonical.search(text):
            continue                      # resolves properly; file path is a fallback
        offenders.append(str(py.relative_to(repo)))

    assert not offenders, (
        "these build a runtime data path from their own file location with no "
        f"canonical resolver — broken in every packaged build: {offenders}"
    )
