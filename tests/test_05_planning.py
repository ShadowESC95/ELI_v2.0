"""
test_05_planning.py
===================
Tests for eli.planning — goals, habits, proposals, autonomy, proactive daemon.
"""
import importlib
import pytest


def test_planning_goal_models_has_dataclass():
    mod = importlib.import_module("eli.planning.goal_models")
    syms = dir(mod)
    matches = [s for s in syms if "Goal" in s]
    assert matches, f"No Goal model in goal_models.py: {syms}"


def test_planning_proactive_daemon_has_class():
    mod = importlib.import_module("eli.planning.proactive_daemon")
    syms = dir(mod)
    matches = [s for s in syms if "Daemon" in s or "Proactive" in s]
    assert matches, f"No daemon class in proactive_daemon.py: {syms}"


def test_planning_db_paths_loadable():
    # Planning has no own db_paths module; it uses the shared resolve_db_paths()
    # (imported by the proactive daemon). Verify that wiring is intact.
    from eli.planning.proactive_daemon import resolve_db_paths
    assert resolve_db_paths is not None
    assert resolve_db_paths() is not None


def test_goal_proposals_reach_the_proposal_queue(monkeypatch, tmp_path):
    from eli.planning import goal_tick, proposal_queue
    seen = {}
    monkeypatch.setattr(proposal_queue, "append_governed_proposal", lambda **kw: seen.update(kw) or {"id": 1})
    out = goal_tick._emit_governed_proposal({"title": "t", "reason": "r"})
    assert out["ok"] is True and "import failed" not in str(out)


def _repo_with_a_change(tmp_path):
    import subprocess
    repo = tmp_path / "proj"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "plan.txt").write_text("water the plants\n", encoding="utf-8")
    subprocess.run(git + ["add", "plan.txt"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "Add the watering plan"], check=True)
    (repo / "plan.txt").write_text("water the plants on Tuesday\n", encoding="utf-8")
    return repo, git


def test_the_git_adapter_runs_read_only_git_for_real(tmp_path):
    """git diff and git status came back empty without running git, so the code monitor (and
    CODE_CHANGES) never saw a change."""
    from eli.planning.proposal_adapters import safe_git_completed
    repo, _ = _repo_with_a_change(tmp_path)
    status = safe_git_completed(["git", "status", "--short"], cwd=str(repo), timeout=10)
    assert status.returncode == 0 and status.stdout == " M plan.txt\n"
    diff = safe_git_completed(["git", "diff"], cwd=str(repo), timeout=10)
    assert "+water the plants on Tuesday" in diff.stdout
    log = safe_git_completed(["git", "log", "--oneline", "-1"], cwd=str(repo), timeout=10)
    assert "Add the watering plan" in log.stdout
    assert not (repo / ".git" / "index.lock").exists()


def test_the_git_adapter_runs_nothing_that_writes(tmp_path):
    from eli.planning.proposal_adapters import safe_git_completed
    repo, _ = _repo_with_a_change(tmp_path)
    for argv in (["git", "commit", "-am", "x"], ["git", "checkout", "--", "plan.txt"],
                 ["git", "-c", "core.editor=x", "log"], ["git", "diff", f"--output={tmp_path / 'out.diff'}"]):
        got = safe_git_completed(argv, cwd=str(repo), timeout=10)
        assert got.returncode == 1 and got.stderr.startswith("not run"), argv
    assert (repo / "plan.txt").read_text(encoding="utf-8") == "water the plants on Tuesday\n"
    assert not (tmp_path / "out.diff").exists()
    elsewhere = tmp_path / "plain"
    elsewhere.mkdir()
    import subprocess
    if subprocess.run(["git", "-C", str(elsewhere), "rev-parse"], capture_output=True).returncode != 0:
        assert safe_git_completed(["git", "status"], cwd=str(elsewhere)).returncode == 128
