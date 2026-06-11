"""FIX_FILE routes Python fixes through the verified CodeAgent (A-E ladder).

Regression for the live run where "fix this file" produced broken code (`def main:`):
the Python fix path now goes through eli.coding.solve (syntax+lint+execution+repo-context+
critique) and writes the verified result with a backup.
"""
import pathlib
import shutil
import tempfile

import pytest


@pytest.fixture
def workspace():
    from eli.execution import executor_enhanced as EX
    root = getattr(EX, "PROJECT_ROOT", pathlib.Path(".").resolve())
    d = pathlib.Path(tempfile.mkdtemp(prefix="fixfile_", dir=str(root / "artifacts")))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_fix_file_uses_codeagent_for_python(workspace, monkeypatch):
    import eli.coding.agent as ca
    from eli.execution import executor_enhanced as EX

    fixed = "def main():\n    print('fixed')\n\n\nif __name__ == '__main__':\n    main()\n"
    called = {}

    def _fake_solve(task, **kw):
        called["task"] = task
        return {"code": fixed, "score": 0.99, "solved": True}

    monkeypatch.setattr(ca, "solve", _fake_solve)

    f = workspace / "broken.py"
    f.write_text("def main:\n  print('broken')\n")          # SyntaxError (bad-patch class)
    r = EX.execute("FIX_FILE", {"path": str(f)})

    assert r.get("ok") is True
    assert "broken.py" in called.get("task", "")            # the agent was actually used
    assert f.read_text().strip() == fixed.strip()            # verified fix written
    assert "def main:" not in f.read_text()                  # the broken form is gone
    assert any(p.name.startswith("broken.py.bak") for p in workspace.iterdir())  # backup made


def test_fix_file_non_python_does_not_invoke_codeagent(workspace, monkeypatch):
    import eli.coding.agent as ca
    from eli.execution import executor_enhanced as EX

    def _boom(task, **kw):
        raise AssertionError("CodeAgent must not run for non-Python files")

    monkeypatch.setattr(ca, "solve", _boom)
    f = workspace / "script.sh"
    f.write_text("echo broken\n")
    # Should not raise from the CodeAgent path (it falls through to the legacy generator,
    # which has no model here → returns a graceful failure, but never calls solve()).
    EX.execute("FIX_FILE", {"path": str(f)})
