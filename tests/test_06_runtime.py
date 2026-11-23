"""
test_06_runtime.py
==================
Tests for eli.runtime — agent, approvals, grounded remediation, self-improvement.
"""
import importlib
import pytest


def _load(mod_path):
    return importlib.import_module(mod_path)


def test_runtime_eli_agent_has_class():
    # The standalone eli.runtime.eli_agent module was removed; its runtime
    # dispatch role is now CognitiveEngine.process, reached via the headless
    # runtime entry point. Verify that entry exists.
    mod = _load("eli.cli.headless")
    assert callable(getattr(mod, "run_headless", None)), \
        f"no runtime dispatch entry (run_headless) in eli.cli.headless: {dir(mod)}"


def test_runtime_grounded_remediation_has_class():
    mod = _load("eli.runtime.grounded_remediation")
    syms = dir(mod)
    # Module is function-based: offer_for_result, try_handle_query are the public API
    matches = [s for s in syms if "Remediat" in s or "Grounded" in s
               or s in ("offer_for_result", "try_handle_query", "capture_executor_failure")]
    assert matches, f"No remediation class/function in grounded_remediation.py: {syms}"


def test_runtime_self_improvement_has_class():
    mod = _load("eli.runtime.self_improvement")
    syms = dir(mod)
    matches = [s for s in syms if "Improve" in s or "Self" in s]
    assert matches, f"No self-improvement class: {syms}"


def test_the_code_monitor_sees_what_changed_between_checks(tmp_path):
    """Its git diff never ran, so every check found nothing and CODE_CHANGES said so."""
    import subprocess
    from eli.runtime.code_monitor import CodeMonitor
    repo = tmp_path / "proj"
    (repo / "eli" / "memory").mkdir(parents=True)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "eli" / "memory" / "store.py").write_text("A = 1\n", encoding="utf-8")
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "first"], check=True)
    mon = CodeMonitor(repo)
    assert mon.use_git
    mon.check()
    (repo / "eli" / "memory" / "store.py").write_text("A = 1\nB = 2\nC = 3\n", encoding="utf-8")
    subprocess.run(git + ["commit", "-q", "-am", "second"], check=True)
    report = mon.check()
    assert [(c.path, c.change_type, c.lines_added) for c in report.changes] == [("eli/memory/store.py", "modified", 2)]
    assert report.has_changes and "memory system" in report.summary()
    assert not list(repo.glob("*code_monitor*")), "the state went into the folder it watches"
    assert mon.state_path.is_file()


def test_code_changes_says_when_it_could_not_look(monkeypatch, tmp_path):
    from eli.execution.executor_enhanced import execute
    from eli.runtime import awareness_boot
    import types
    plain = tmp_path / "installed"
    plain.mkdir()
    state = awareness_boot.AwarenessState()
    state._code_mon = types.SimpleNamespace(use_git=False, repo_root=plain)   # what CodeMonitor is there
    monkeypatch.setattr(awareness_boot, "_awareness", state)
    text = execute("CODE_CHANGES", {})["response"]
    assert "can't see code changes" in text and str(plain) in text



def test_what_the_code_monitor_saw_is_kept_in_the_data_folder_not_the_tree():
    """Kept in the source tree, every engine start in a test or an eval wrote .code_monitor_state.json
    into the checkout."""
    from eli.core.paths import data_dir, project_root
    from eli.runtime.code_monitor import CodeMonitor
    for mon in (CodeMonitor(), CodeMonitor(project_root())):        # awareness_boot names the install's root
        assert mon.state_path.parent == data_dir() / "runtime"
