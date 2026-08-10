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


# ── append-only logs must not grow forever ──────────────────────────────────
def test_world_logs_are_trimmed(tmp_path):
    """actions.jsonl reached 41MB / 80,576 lines and events.jsonl 6.2MB on a
    normal desktop. Corrupt state backups were pruned; the logs never were, and
    nothing reads them whole — the panel and journal want the recent tail."""
    import json as _json
    from eli.world.persistence import storage as st

    p = tmp_path / "actions.jsonl"
    p.write_text("".join(_json.dumps({"i": i}) + "\n" for i in range(5000)), encoding="utf-8")

    st._jsonl_since_check[str(p)] = st._JSONL_CHECK_EVERY
    st._trim_jsonl(p, max_lines=1000)

    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1000
    assert _json.loads(lines[-1])["i"] == 4999, "must keep the NEWEST entries"
    assert all(_json.loads(l) for l in lines), "a size-based trim would split a line"


def test_trim_leaves_no_scratch_file(tmp_path):
    import json as _json
    from eli.world.persistence import storage as st

    p = tmp_path / "events.jsonl"
    p.write_text("".join(_json.dumps({"i": i}) + "\n" for i in range(3000)), encoding="utf-8")
    st._jsonl_since_check[str(p)] = st._JSONL_CHECK_EVERY
    st._trim_jsonl(p, max_lines=500)

    assert not list(tmp_path.glob("*.trim"))


def test_trim_is_not_run_on_every_append(tmp_path):
    """It rewrites the file, so it must be amortised, not per-write."""
    import json as _json
    from eli.world.persistence import storage as st

    p = tmp_path / "a.jsonl"
    p.write_text("".join(_json.dumps({"i": i}) + "\n" for i in range(3000)), encoding="utf-8")
    st._jsonl_since_check[str(p)] = 0
    st._trim_jsonl(p, max_lines=100)

    assert sum(1 for _ in p.open(encoding="utf-8")) == 3000, "trimmed on the very first append"


def test_trim_survives_a_missing_file(tmp_path):
    from eli.world.persistence import storage as st
    st._jsonl_since_check[str(tmp_path / "nope.jsonl")] = st._JSONL_CHECK_EVERY
    st._trim_jsonl(tmp_path / "nope.jsonl")   # must not raise


def test_first_append_in_a_process_always_checks(tmp_path):
    """The amortisation counter is per-process, so "every 250 appends" on its own
    means a run that appends fewer than 250 entries never trims — and the file
    grows across restarts untouched. events.jsonl was found at 23,179 lines
    against a 20,000 cap this way, while the busier actions.jsonl was fine."""
    import json as _json
    from eli.world.persistence import storage as st

    p = tmp_path / "events.jsonl"
    p.write_text("".join(_json.dumps({"i": i}) + "\n" for i in range(3000)), encoding="utf-8")
    st._jsonl_since_check.pop(str(p), None)   # as if this process just started

    st._trim_jsonl(p, max_lines=1000)

    assert sum(1 for _ in p.open(encoding="utf-8")) == 1000, (
        "an oversized log survived a fresh process untouched"
    )


# ── schema drift must not destroy the world ─────────────────────────────────
# Five `eli_world_state.corrupt_*` backups accumulated between 2026-07-05 and
# 2026-08-05. Three carry a complete JSON document followed by a single stray
# "}" — the signature of two writers sharing one fixed ".tmp" name with
# independent file offsets, fixed in ee43548 (all five predate it).
#
# The other two parse as perfectly valid JSON. Those were not corrupt at all:
# `AwarenessState(**data)` raises TypeError the instant the saved state carries
# a field the dataclass no longer declares, load() caught *every* exception,
# renamed the user's world to ".corrupt_*" and returned an empty default. One
# renamed attribute in a release would wipe every existing user's rooms,
# objects, goals and habits on upgrade.

def _drifted(**extra):
    base = {
        "awareness": {"focus": 0.9, "curiosity": 0.3},
        "avatar": {"room": "lab", "posture": "seated"},
        "objects": {"lamp": {"object_id": "lamp", "name": "lamp",
                             "object_type": "light", "room": "lab", "x": 3.0}},
    }
    for section, fields in extra.items():
        base[section].update(fields)
    return base


def test_unknown_awareness_field_does_not_wipe_the_world():
    from eli.world.persistence.storage import _state_from_dict
    state = _state_from_dict(_drifted(awareness={"retired_field": 1}))
    assert state.awareness.focus == 0.9, "known values must survive the drop"


def test_unknown_avatar_field_keeps_the_room():
    """The originally reported symptom: room silently reset to core_room."""
    from eli.world.persistence.storage import _state_from_dict
    state = _state_from_dict(_drifted(avatar={"gone_field": 2}))
    assert state.avatar.room == "lab"


def test_unknown_object_field_keeps_the_object():
    from eli.world.persistence.storage import _state_from_dict
    state = _state_from_dict(_drifted(objects={"lamp": {
        "object_id": "lamp", "name": "lamp", "object_type": "light",
        "room": "lab", "x": 3.0, "removed_field": 9}}))
    assert "lamp" in state.objects and state.objects["lamp"].x == 3.0


def test_one_unusable_record_does_not_discard_the_others():
    """A record missing a *required* field is dropped alone, not with the rest."""
    from eli.world.persistence.storage import _state_from_dict
    state = _state_from_dict({"objects": {
        "good": {"object_id": "good", "name": "g", "object_type": "light", "room": "lab"},
        "bad": {"name": "no object_id"},
    }})
    assert "good" in state.objects and "bad" not in state.objects


def test_valid_json_is_never_filed_as_corrupt(tmp_path, monkeypatch):
    """The exact loss: JSON parsed fine, so the user's data was intact on disk,
    and load() renamed it away regardless."""
    import json as _json
    from eli.world.persistence import storage as st

    p = tmp_path / "eli_world_state.json"
    p.write_text(_json.dumps({"world_name": "mine", "avatar": {"room": "lab"}}), encoding="utf-8")

    def explode(_data):
        raise TypeError("a build that cannot map this schema")

    monkeypatch.setattr(st, "_state_from_dict", explode)
    st.EliWorldStorage(state_path=p).load()

    assert p.exists(), "a parseable world state was renamed away"
    assert not list(tmp_path.glob("*.corrupt_*")), "parseable state filed as corrupt"


def test_unparseable_json_is_still_backed_up(tmp_path):
    """The salvage path must not swallow real corruption silently."""
    from eli.world.persistence import storage as st

    p = tmp_path / "eli_world_state.json"
    p.write_text('{"world_name": "mine"}}', encoding="utf-8")   # the stray-brace signature

    st.EliWorldStorage(state_path=p).load()

    assert list(tmp_path.glob("*.corrupt_*")), "genuinely corrupt state was not preserved"


def test_second_append_does_not_re_trim(tmp_path):
    """First-append checking must not turn into trimming on every write."""
    import json as _json
    from eli.world.persistence import storage as st

    p = tmp_path / "b.jsonl"
    p.write_text("".join(_json.dumps({"i": i}) + "\n" for i in range(3000)), encoding="utf-8")
    st._jsonl_since_check.pop(str(p), None)

    st._trim_jsonl(p, max_lines=1000)          # trims to 1000
    with p.open("a", encoding="utf-8") as f:   # a normal append after it
        f.write(_json.dumps({"i": "new"}) + "\n")
    st._trim_jsonl(p, max_lines=1000)          # must NOT rewrite again

    assert sum(1 for _ in p.open(encoding="utf-8")) == 1001
