"""Runtime state must live in the user's data dir, not the installation.

`project_root()` is the source tree in dev and the READ-ONLY AppImage mount on a
packaged install, so `project_root()/artifacts/...` silently fails to persist —
or reads a file that was written somewhere else entirely.

Live at 2.3.2: the model loaded at ctx=8192 and the streaming guard still logged
"truncated to fit n_ctx=2048", trimming memory context to 400 chars and capping
output at 128 tokens. `_effective_n_ctx()` read the runtime snapshot from
project_root()/artifacts while the loader had written it to
~/.local/share/ELI_v2/artifacts — so the read never found it and fell through to
a conservative default. ELI was budgeting every prompt against a context it was
not using.
"""
import importlib

import pytest

from eli.core import paths


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_DATA_DIR", str(tmp_path))
    for fn in ("data_dir", "artifacts_dir"):
        f = getattr(paths, fn, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()
    yield tmp_path
    for fn in ("data_dir", "artifacts_dir"):
        f = getattr(paths, fn, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()


def _reload(name):
    import sys
    mod = importlib.import_module(name)
    return importlib.reload(mod)


@pytest.mark.parametrize("module,func", [
    ("eli.planning.autonomy_scheduler", "scheduler_state_path"),
    ("eli.execution.operator_actions", "queue_path"),
    ("eli.planning.attention_queue", "attention_path"),
    ("eli.planning.attention_queue", "suppression_path"),
])
def test_runtime_state_lives_in_the_data_dir(module, func, data_dir):
    m = _reload(module)
    p = getattr(m, func)()
    assert str(p).startswith(str(data_dir)), f"{module}.{func}() escaped to {p}"


def test_the_snapshot_is_read_from_where_it_is_written():
    """The loader writes runtime_snapshot.json to the artifacts dir; the budget
    guard must read it from the same place, not from the installation."""
    import inspect
    from eli.kernel.engine import CognitiveEngine
    src = inspect.getsource(CognitiveEngine._effective_n_ctx)
    # Strip comments first. Five times this session a test matched the very
    # comment describing the bug and passed against code that still had it.
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "artifacts_dir" in code, "the snapshot read still uses the project root"
    assert "project_root" not in code


def test_the_hardware_profile_is_read_from_the_data_dir():
    import inspect
    from eli.core import hardware_profile
    src = inspect.getsource(hardware_profile)
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    i = code.index("runtime_hardware_profile.json")
    window = code[max(0, i - 300):i]
    assert "artifacts_dir" in window and "project_root" not in window
