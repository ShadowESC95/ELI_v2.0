"""
test_06_runtime.py
==================
Tests for eli.runtime — agent, approvals, grounded remediation, self-improvement.
"""
import importlib
import pytest


def _load(mod_path):
    return importlib.import_module(mod_path)


def test_runtime_package_init():
    assert _load("eli.runtime") is not None


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


def test_runtime_security_loadable():
    assert _load("eli.runtime.security") is not None


def test_runtime_approval_engine_loadable():
    assert _load("eli.runtime.approval_engine") is not None


def test_runtime_authority_gate_loadable():
    assert _load("eli.runtime.authority_gate") is not None



def test_runtime_awareness_boot_loadable():
    assert _load("eli.runtime.awareness_boot") is not None


def test_runtime_capability_sync_loadable():
    assert _load("eli.runtime.capability_sync") is not None


def test_runtime_code_monitor_loadable():
    assert _load("eli.runtime.code_monitor") is not None


def test_runtime_control_contracts_loadable():
    assert _load("eli.runtime.control_contracts") is not None


def test_runtime_evidence_arbitration_loadable():
    assert _load("eli.runtime.evidence_arbitration") is not None


def test_runtime_final_response_provider_loadable():
    assert _load("eli.runtime.final_response_provider") is not None


def test_runtime_incident_log_loadable():
    assert _load("eli.runtime.incident_log") is not None


def test_runtime_last_trace_loadable():
    assert _load("eli.runtime.last_trace") is not None


def test_runtime_live_introspection_loadable():
    assert _load("eli.runtime.live_introspection") is not None



def test_runtime_operator_feed_loadable():
    assert _load("eli.runtime.operator_feed") is not None



def test_runtime_operator_state_loadable():
    assert _load("eli.runtime.operator_state") is not None



def test_runtime_persistence_gate_loadable():
    assert _load("eli.runtime.persistence_gate") is not None


def test_runtime_personal_memory_surface_loadable():
    assert _load("eli.runtime.personal_memory_surface") is not None


def test_runtime_pipeline_models_loadable():
    assert _load("eli.runtime.pipeline_models") is not None


def test_runtime_profile_extractor_loadable():
    assert _load("eli.runtime.profile_extractor") is not None


def test_runtime_reflection_loadable():
    assert _load("eli.runtime.reflection") is not None



def test_runtime_response_contracts_loadable():
    assert _load("eli.runtime.response_contracts") is not None



def test_runtime_response_policy_loadable():
    assert _load("eli.runtime.response_policy") is not None



def test_runtime_self_model_refresh_loadable():
    assert _load("eli.runtime.self_model_refresh") is not None



def test_runtime_stage_packets_loadable():
    assert _load("eli.runtime.stage_packets") is not None


def test_runtime_stage_packet_store_loadable():
    assert _load("eli.runtime.stage_packet_store") is not None


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
