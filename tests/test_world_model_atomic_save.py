"""save_world_model() used to write_text() the state file directly. A crash
or power loss mid-write (or a second writer landing between two calls --
_LOCK only serialises within one process) could leave a truncated or
interleaved eli/kernel/world_model.py::world_model.json. The sibling world
state file (eli/world/persistence/storage.py, a separate/legacy-adjacent
system, see EliWorldAutonomyEngine) already hit and fixed exactly this with
a unique-tmp-name + fsync + atomic-replace pattern; this applies the same
fix here instead of leaving a second, weaker implementation of the same
kind of file next to a hardened one.
"""
import json

import eli.kernel.world_model as wm


def _isolate(monkeypatch, tmp_path):
    path = tmp_path / "world_model.json"
    monkeypatch.setattr(wm, "_world_model_path", lambda: path)
    monkeypatch.setattr(wm, "_WORLD", None, raising=False)
    return path


def test_save_and_load_round_trips(monkeypatch, tmp_path):
    path = _isolate(monkeypatch, tmp_path)
    wm.set_preferred_name("Jay", confidence=0.9)
    monkeypatch.setattr(wm, "_WORLD", None, raising=False)  # force a real reload
    loaded = wm.load_world_model(force_reload=True)
    assert loaded.identity.preferred_name == "Jay"
    assert loaded.identity.confidence == 0.9
    assert path.exists()


def test_save_leaves_no_stray_tmp_files(monkeypatch, tmp_path):
    path = _isolate(monkeypatch, tmp_path)
    wm.save_world_model(wm.WorldModel())
    leftovers = list(tmp_path.glob(f"{path.stem}.*.tmp"))
    assert leftovers == [], f"atomic write left scratch file(s) behind: {leftovers}"


def test_a_write_failure_does_not_corrupt_the_existing_file(monkeypatch, tmp_path):
    """The write happens to a unique scratch file first; only a clean write
    gets swapped in. Simulate a failure during the write and confirm the
    previously-saved, valid file survives untouched."""
    path = _isolate(monkeypatch, tmp_path)
    wm.save_world_model(wm.WorldModel(schema_version=1))
    original = path.read_text(encoding="utf-8")

    import os as _os
    real_fdopen = _os.fdopen

    def _boom_fdopen(*a, **k):
        raise OSError("simulated disk failure mid-write")

    monkeypatch.setattr(wm.os, "fdopen", _boom_fdopen)
    try:
        wm.save_world_model(wm.WorldModel(schema_version=99))
        assert False, "expected the simulated write failure to raise"
    except OSError:
        pass
    monkeypatch.setattr(wm.os, "fdopen", real_fdopen)

    assert path.read_text(encoding="utf-8") == original, (
        "a failed write corrupted or replaced the previously-good file"
    )
    assert json.loads(original)["schema_version"] == 1
    # No scratch file left behind by the failed attempt either.
    leftovers = list(tmp_path.glob(f"{path.stem}.*.tmp"))
    assert leftovers == []
